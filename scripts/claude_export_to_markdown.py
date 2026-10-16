"""
Claude conversations.json to individual Markdown files.

This is a local/offline converter for Claude export batches, where
conversations are stored as:

    conversations.json
    memories.json
    users.json

Default behaviour:
- writes one Markdown file per conversation
- includes conversation and message timestamps
- skips Claude thinking blocks
- skips tool payloads unless --include-tools is used
- does not overwrite existing files unless --overwrite is used

No network calls. No upload. Local files only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The modules are usable both as package imports and standalone scripts.
try:
    from .csv_safety import spreadsheet_safe_row
except ImportError:  # direct: python scripts/<converter>.py
    from csv_safety import spreadsheet_safe_row

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - old Python fallback
    ZoneInfo = None  # type: ignore


DEFAULT_TIMEZONE = "UTC"


@dataclass(frozen=True)
class RenderOptions:
    include_thinking: bool = False
    include_tools: bool = False
    include_empty_messages: bool = False
    timezone_name: str = DEFAULT_TIMEZONE


def sanitize_filename(value: str, fallback: str = "untitled", max_len: int = 90) -> str:
    """Make a Windows-safe filename component."""
    value = value or fallback
    value = value.encode("ascii", errors="ignore").decode("ascii")
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        value = fallback
    return value[:max_len].rstrip(" .") or fallback


def parse_timestamp(value: Any) -> datetime | None:
    """Parse Claude ISO timestamps into timezone-aware UTC datetimes."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: Any, timezone_name: str = DEFAULT_TIMEZONE) -> str:
    """Format a timestamp as local time with UTC reference."""
    dt_utc = parse_timestamp(value)
    if dt_utc is None:
        return "Unknown"

    local_text = ""
    if ZoneInfo is not None and timezone_name:
        try:
            dt_local = dt_utc.astimezone(ZoneInfo(timezone_name))
            local_text = dt_local.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            local_text = ""

    utc_text = dt_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    if local_text and local_text != utc_text:
        return f"{local_text} ({utc_text})"
    return utc_text


def filename_timestamp(value: Any) -> str:
    dt_utc = parse_timestamp(value)
    if dt_utc is None:
        return "unknown-date"
    return dt_utc.strftime("%Y-%m-%d_%H%M%S")


def normalise_sender(sender: str | None) -> str:
    if not sender:
        return "unknown"
    sender = sender.lower().strip()
    if sender == "human":
        return "user"
    return sender


def extract_text_blocks(message: dict[str, Any], options: RenderOptions) -> list[str]:
    """Extract clean visible text from a Claude message."""
    blocks = message.get("content") or []
    output: list[str] = []

    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")

        if block_type == "text":
            text = block.get("text") or ""
            if text.strip():
                output.append(text.strip())
            continue

        if block_type == "thinking":
            if options.include_thinking:
                text = block.get("thinking") or block.get("text") or ""
                if text.strip():
                    output.append("[thinking block]\n\n" + text.strip())
            continue

        if block_type in {"tool_use", "tool_result", "token_budget"}:
            if options.include_tools:
                output.append(render_tool_block(block))
            continue

    if output:
        return output

    # Fallback only when there are no structured blocks. Avoid using assistant
    # message["text"] when it appears to be made solely of thinking/tool content.
    fallback = message.get("text") or ""
    if fallback.strip() and (options.include_empty_messages or not blocks):
        return [fallback.strip()]

    return []


def render_tool_block(block: dict[str, Any]) -> str:
    block_type = block.get("type", "tool")
    if block_type == "tool_use":
        name = block.get("name") or block.get("id") or "unknown"
        return f"[tool_use: {name}]"
    if block_type == "tool_result":
        name = block.get("name") or block.get("tool_use_id") or "unknown"
        content = block.get("content")
        if isinstance(content, str):
            preview = content[:500]
        else:
            preview = json.dumps(content, ensure_ascii=False)[:500]
        return f"[tool_result: {name}]\n\n```text\n{preview}\n```"
    if block_type == "token_budget":
        return "[token_budget block omitted]"
    return f"[{block_type} block omitted]"


def markdown_escape_title(title: str) -> str:
    return title.replace("\n", " ").strip() or "Untitled Claude Conversation"


def conversation_title(conv: dict[str, Any], index: int) -> str:
    return (
        conv.get("name")
        or conv.get("title")
        or conv.get("summary")
        or f"Untitled Claude Conversation {index:04d}"
    )


def iter_messages(conv: dict[str, Any]) -> list[dict[str, Any]]:
    messages = conv.get("chat_messages") or []
    clean = [m for m in messages if isinstance(m, dict)]
    clean.sort(key=lambda m: parse_timestamp(m.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
    return clean


def conversation_to_markdown(conv: dict[str, Any], index: int, options: RenderOptions) -> tuple[str, int]:
    title = markdown_escape_title(conversation_title(conv, index))
    uuid = conv.get("uuid") or "unknown"
    created_at = conv.get("created_at")
    updated_at = conv.get("updated_at")
    messages = iter_messages(conv)

    lines: list[str] = [
        f"# {title}",
        "",
        "Source: Claude export",
        f"Conversation number: {index:04d}",
        f"Conversation UUID: `{uuid}`",
        f"Created: {format_timestamp(created_at, options.timezone_name)}",
        f"Updated: {format_timestamp(updated_at, options.timezone_name)}",
        f"Message count: {len(messages)}",
    ]

    summary = conv.get("summary") or ""
    if summary.strip():
        lines.extend(["", "## Summary", "", summary.strip()])

    lines.extend(["", "---", ""])

    rendered_count = 0
    for message_number, message in enumerate(messages, 1):
        sender = normalise_sender(message.get("sender"))
        timestamp = format_timestamp(message.get("created_at"), options.timezone_name)
        message_uuid = message.get("uuid") or "unknown"
        parts = extract_text_blocks(message, options)

        if not parts and not options.include_empty_messages:
            continue

        rendered_count += 1
        heading = f"## {message_number:04d} | {sender.upper()} | {timestamp}"
        lines.extend([heading, "", f"Message UUID: `{message_uuid}`", ""])

        if parts:
            lines.append("\n\n".join(parts).rstrip())
        else:
            lines.append("_No visible text in this message._")

        attachments = message.get("attachments") or []
        files = message.get("files") or []
        if attachments or files:
            lines.extend(["", "### Attachments / Files", ""])
            for item in attachments:
                lines.append("- attachment: " + describe_attachment(item))
            for item in files:
                lines.append("- file: " + describe_attachment(item))

        lines.extend(["", "---", ""])

    if rendered_count == 0:
        lines.extend(["_No visible text messages rendered._", ""])

    return "\n".join(lines).rstrip() + "\n", rendered_count


def describe_attachment(item: Any) -> str:
    if isinstance(item, dict):
        name = item.get("file_name") or item.get("filename") or item.get("name") or item.get("id") or "unknown"
        mime = item.get("mime_type") or item.get("type")
        if mime:
            return f"{name} ({mime})"
        return str(name)
    return str(item)


def load_conversations(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Claude conversations.json should contain a list of conversations")
    return [item for item in data if isinstance(item, dict)]


def autodetect_input(start: Path) -> Path | None:
    candidates = [
        start / "conversations.json",
        start / "claude" / "conversations.json",
    ]
    claude_dir = start / "claude"
    if claude_dir.exists():
        candidates.extend(sorted(claude_dir.glob("*/conversations.json")))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def parse_date_filter(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Invalid date {value!r}, use YYYY-MM-DD") from exc
    if end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed.replace(tzinfo=timezone.utc)


def filter_conversations(
    conversations: list[dict[str, Any]],
    title_filter: str | None,
    start_date: datetime | None,
    end_date: datetime | None,
) -> list[dict[str, Any]]:
    title_filter_lower = title_filter.lower() if title_filter else None
    output: list[dict[str, Any]] = []

    for conv in conversations:
        title = conversation_title(conv, 0).lower()
        if title_filter_lower and title_filter_lower not in title:
            continue

        created = parse_timestamp(conv.get("created_at"))
        if start_date and created and created < start_date:
            continue
        if end_date and created and created > end_date:
            continue

        output.append(conv)

    return output


def write_index_csv(rows: list[dict[str, Any]], output_dir: Path) -> None:
    index_path = output_dir / "_index.csv"
    with index_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "number",
                "title",
                "uuid",
                "created_at",
                "updated_at",
                "message_count",
                "rendered_message_count",
                "file",
            ],
        )
        writer.writeheader()
        writer.writerows(spreadsheet_safe_row(row) for row in rows)


def process_claude_export(
    input_json_path: Path,
    output_dir: Path | None = None,
    overwrite: bool = False,
    quiet: bool = False,
    title_filter: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int | None = None,
    options: RenderOptions | None = None,
) -> dict[str, Any]:
    options = options or RenderOptions()
    input_json_path = input_json_path.resolve()
    output_dir = output_dir or (input_json_path.parent / "claude_conversations_markdown")
    output_dir.mkdir(parents=True, exist_ok=True)

    conversations = load_conversations(input_json_path)
    conversations = filter_conversations(conversations, title_filter, start_date, end_date)
    conversations.sort(key=lambda c: parse_timestamp(c.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
    if limit is not None:
        conversations = conversations[:limit]

    if not quiet:
        print("Claude Conversations Processor")
        print(f"Input:  {input_json_path}")
        print(f"Output: {output_dir.resolve()}")
        print(f"Mode:   {'overwrite' if overwrite else 'skip existing'}")
        print(f"Count:  {len(conversations)}")

    rows: list[dict[str, Any]] = []
    saved = skipped = errors = 0

    for index, conv in enumerate(conversations, 1):
        try:
            title = conversation_title(conv, index)
            uuid = conv.get("uuid") or f"conversation-{index:04d}"
            stamp = filename_timestamp(conv.get("created_at"))
            safe_title = sanitize_filename(title)
            filename = f"{stamp}_{index:04d}_{safe_title}_{str(uuid)[:8]}.md"
            output_file = output_dir / filename

            content, rendered_count = conversation_to_markdown(conv, index, options)
            try:
                if overwrite:
                    output_file.write_text(content, encoding="utf-8")
                else:
                    with output_file.open(
                        "x", encoding="utf-8", newline="\n"
                    ) as handle:
                        handle.write(content)
                saved += 1
            except FileExistsError:
                skipped += 1

            rows.append(
                {
                    "number": f"{index:04d}",
                    "title": title,
                    "uuid": uuid,
                    "created_at": conv.get("created_at") or "",
                    "updated_at": conv.get("updated_at") or "",
                    "message_count": len(iter_messages(conv)),
                    "rendered_message_count": rendered_count,
                    "file": output_file.name,
                }
            )

            if not quiet and index % 25 == 0:
                print(f"  processed {index}/{len(conversations)}")
        except Exception as exc:
            errors += 1
            if not quiet:
                print(f"  error on conversation {index}: {exc}")

    write_index_csv(rows, output_dir)

    if not quiet:
        print("Done")
        print(f"Saved:   {saved}")
        print(f"Skipped: {skipped}")
        print(f"Errors:  {errors}")
        print(f"Index:   {output_dir / '_index.csv'}")

    return {
        "total": len(conversations),
        "saved": saved,
        "skipped": skipped,
        "errors": errors,
        "output_dir": str(output_dir.resolve()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert Claude export conversations.json into individual timestamped Markdown files."
    )
    parser.add_argument("-i", "--input", help="Path to Claude conversations.json")
    parser.add_argument("-o", "--output", help="Output directory")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Markdown files")
    parser.add_argument("--title", help="Filter conversations by title substring")
    parser.add_argument("--start-date", help="Filter by created date, YYYY-MM-DD")
    parser.add_argument("--end-date", help="Filter by created date, YYYY-MM-DD")
    parser.add_argument("--limit", type=int, help="Maximum conversations to render")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help=f"Display timezone, default {DEFAULT_TIMEZONE}")
    parser.add_argument("--include-thinking", action="store_true", help="Include Claude thinking blocks")
    parser.add_argument("--include-tools", action="store_true", help="Include short tool-use/tool-result summaries")
    parser.add_argument("--include-empty", action="store_true", help="Keep messages with no visible rendered text")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.input:
        input_path = Path(args.input)
    else:
        detected = autodetect_input(Path.cwd())
        if detected is None:
            print("Error: could not find Claude conversations.json. Use -i/--input.", file=sys.stderr)
            return 1
        input_path = detected

    if not input_path.exists():
        print(f"Error: input not found: {input_path}", file=sys.stderr)
        return 1

    try:
        start_date = parse_date_filter(args.start_date)
        end_date = parse_date_filter(args.end_date, end_of_day=True)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    options = RenderOptions(
        include_thinking=args.include_thinking,
        include_tools=args.include_tools,
        include_empty_messages=args.include_empty,
        timezone_name=args.timezone,
    )

    result = process_claude_export(
        input_json_path=input_path,
        output_dir=Path(args.output) if args.output else None,
        overwrite=args.overwrite,
        quiet=args.quiet,
        title_filter=args.title,
        start_date=start_date,
        end_date=end_date,
        limit=args.limit,
        options=options,
    )

    return 0 if result["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
