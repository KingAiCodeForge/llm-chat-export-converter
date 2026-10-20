"""
ChatGPT conversations.json to individual Markdown files.

This is a local/offline converter for ChatGPT export files.
It turns conversations.json into cleaner files for search, review and LLM use:

- timestamped filenames
- message timestamps in a configurable display timezone plus UTC
- one Markdown file per conversation
- _index.csv for searching/sorting
- ASCII-safe Windows filenames
- skip-existing default, with --overwrite when needed
- optional legacy filename mode for older workflows

No network calls. No upload. Local files only.
"""

from __future__ import annotations

import argparse
import csv
import json
import io
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The modules are usable both as package imports and standalone scripts.
try:
    from .csv_safety import spreadsheet_safe_row
    from .output_safety import check_destination, write_text
except ImportError:  # direct: python scripts/<converter>.py
    from csv_safety import spreadsheet_safe_row
    from output_safety import check_destination, write_text

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - old Python fallback
    ZoneInfo = None  # type: ignore


DEFAULT_TIMEZONE = "UTC"


@dataclass(frozen=True)
class RenderOptions:
    include_system: bool = True
    include_tools: bool = False
    include_empty_messages: bool = False
    timezone_name: str = DEFAULT_TIMEZONE


def sanitize_filename(value: str, fallback: str = "untitled", max_len: int = 90) -> str:
    """Make a Windows-safe ASCII filename component."""
    value = value or fallback
    value = value.encode("ascii", errors="ignore").decode("ascii")
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        value = fallback
    return value[:max_len].rstrip(" .") or fallback


def parse_timestamp(value: Any) -> datetime | None:
    """Parse ChatGPT Unix timestamps or ISO timestamps into UTC datetimes."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                return datetime.fromtimestamp(float(text), tz=timezone.utc)
            except Exception:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


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


def markdown_title(title: str) -> str:
    return (title or "Untitled ChatGPT Conversation").replace("\n", " ").strip()


def conversation_title(conv: dict[str, Any], index: int) -> str:
    return conv.get("title") or conv.get("name") or f"Untitled ChatGPT Conversation {index:04d}"


def conversation_id(conv: dict[str, Any], index: int) -> str:
    return str(conv.get("id") or conv.get("conversation_id") or f"conversation-{index:04d}")


def normalise_role(role: str | None) -> str:
    role = (role or "unknown").lower().strip()
    if role in {"human"}:
        return "user"
    return role


def part_to_text(part: Any, options: RenderOptions) -> str | None:
    """Convert one ChatGPT content part into Markdown text where safe."""
    if isinstance(part, str):
        text = part.strip()
        return text or None

    if isinstance(part, dict):
        part_type = part.get("type") or part.get("content_type") or "part"

        if part_type in {"text", "input_text", "output_text"}:
            text = part.get("text") or part.get("content") or ""
            text = text.strip() if isinstance(text, str) else ""
            return text or None

        if part_type in {"image_asset_pointer", "image", "input_image"}:
            pointer = part.get("asset_pointer") or part.get("url") or part.get("file_id") or "image"
            return f"[image: {pointer}]"

        if part_type in {"audio", "input_audio"}:
            pointer = part.get("asset_pointer") or part.get("file_id") or "audio"
            return f"[audio: {pointer}]"

        if options.include_tools:
            preview = json.dumps(part, ensure_ascii=False)[:800]
            return f"[content part: {part_type}]\n\n```json\n{preview}\n```"

    return None


def extract_message_text(message: dict[str, Any], options: RenderOptions) -> str:
    content = message.get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else None
    output: list[str] = []

    if isinstance(parts, list):
        for part in parts:
            text = part_to_text(part, options)
            if text:
                output.append(text)

    if output:
        return "\n\n".join(output).strip()

    if options.include_tools:
        content_type = content.get("content_type") if isinstance(content, dict) else type(content).__name__
        preview = json.dumps(content, ensure_ascii=False)[:1000]
        if preview and preview != "{}":
            return f"[message content: {content_type}]\n\n```json\n{preview}\n```"

    return ""


def extract_messages(conv: dict[str, Any], options: RenderOptions) -> list[dict[str, Any]]:
    """Extract visible messages from a ChatGPT mapping tree."""
    mapping = conv.get("mapping") or {}
    messages: list[dict[str, Any]] = []

    if not isinstance(mapping, dict):
        return messages

    for node_id, node in mapping.items():
        if not isinstance(node, dict):
            continue
        message = node.get("message")
        if not isinstance(message, dict):
            continue

        role = normalise_role((message.get("author") or {}).get("role"))
        if role == "system" and not options.include_system:
            continue
        if role in {"tool", "function"} and not options.include_tools:
            continue

        text = extract_message_text(message, options)
        if not text and not options.include_empty_messages:
            continue

        timestamp = message.get("create_time") or message.get("update_time") or conv.get("create_time")
        messages.append(
            {
                "node_id": node_id,
                "message_id": message.get("id") or node_id,
                "role": role,
                "timestamp": timestamp,
                "update_time": message.get("update_time"),
                "content": text,
            }
        )

    messages.sort(
        key=lambda item: (
            parse_timestamp(item.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
            str(item.get("node_id") or ""),
        )
    )
    return messages


def conversation_to_markdown(conv: dict[str, Any], index: int, options: RenderOptions) -> tuple[str, int]:
    title = markdown_title(conversation_title(conv, index))
    conv_id = conversation_id(conv, index)
    create_time = conv.get("create_time")
    update_time = conv.get("update_time")
    messages = extract_messages(conv, options)

    lines: list[str] = [
        f"# {title}",
        "",
        "Source: ChatGPT export",
        f"Conversation number: {index:04d}",
        f"Conversation ID: `{conv_id}`",
        f"Created: {format_timestamp(create_time, options.timezone_name)}",
        f"Updated: {format_timestamp(update_time, options.timezone_name)}",
        f"Rendered message count: {len(messages)}",
        "",
        "---",
        "",
    ]

    if not messages:
        lines.extend(["_No visible text messages rendered._", ""])
        return "\n".join(lines).rstrip() + "\n", 0

    for message_number, message in enumerate(messages, 1):
        role = str(message.get("role") or "unknown").upper()
        timestamp = format_timestamp(message.get("timestamp"), options.timezone_name)
        message_id = message.get("message_id") or "unknown"

        lines.extend(
            [
                f"## {message_number:04d} | {role} | {timestamp}",
                "",
                f"Message ID: `{message_id}`",
                "",
            ]
        )

        content = (message.get("content") or "").strip()
        lines.append(content if content else "_No visible text in this message._")
        lines.extend(["", "---", ""])

    return "\n".join(lines).rstrip() + "\n", len(messages)


def load_conversations(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("ChatGPT conversations.json should contain a list of conversations")
    return [item for item in data if isinstance(item, dict)]


def autodetect_input(start: Path) -> Path | None:
    candidates = [
        start / "conversations.json",
        start / "latest_export" / "conversations.json",
        start / "chatgpt" / "conversations.json",
    ]
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

        created = parse_timestamp(conv.get("create_time"))
        if start_date and created and created < start_date:
            continue
        if end_date and created and created > end_date:
            continue

        output.append(conv)

    return output


def write_index_csv(rows: list[dict[str, Any]], output_dir: Path, *, overwrite: bool = False) -> None:
    index_path = output_dir / "_index.csv"
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(
        handle,
        fieldnames=[
            "number",
            "title",
            "id",
            "created_at",
            "updated_at",
            "rendered_message_count",
            "file",
        ],
    )
    writer.writeheader()
    writer.writerows(spreadsheet_safe_row(row) for row in rows)
    write_text(index_path, handle.getvalue(), overwrite=overwrite)


def output_filename(conv: dict[str, Any], index: int, legacy: bool) -> str:
    title = conversation_title(conv, index)
    safe_title = sanitize_filename(title)
    conv_id = conversation_id(conv, index)

    if legacy:
        return f"{index:04d}_{safe_title}.md"

    stamp = filename_timestamp(conv.get("create_time"))
    return f"{stamp}_{index:04d}_{safe_title}_{sanitize_filename(conv_id[:8])}.md"


def process_chatgpt_export(
    input_json_path: Path,
    output_dir: Path | None = None,
    overwrite: bool = False,
    quiet: bool = False,
    title_filter: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int | None = None,
    legacy_filenames: bool = False,
    options: RenderOptions | None = None,
) -> dict[str, Any]:
    options = options or RenderOptions()
    input_json_path = input_json_path.expanduser().resolve()
    output_dir = (output_dir or (input_json_path.parent / "chatgpt_export_markdown")).expanduser().resolve()
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start date must be on or before end date")
    check_destination(output_dir / "_index.csv", input_json_path, overwrite=overwrite)

    conversations = load_conversations(input_json_path)
    conversations = filter_conversations(conversations, title_filter, start_date, end_date)
    conversations.sort(
        key=lambda conv: (
            parse_timestamp(conv.get("create_time")) or datetime.min.replace(tzinfo=timezone.utc),
            conversation_id(conv, 0),
        )
    )
    if limit is not None:
        conversations = conversations[:limit]

    output_dir.mkdir(parents=True, exist_ok=True)

    if not quiet:
        print("ChatGPT Conversations Processor v3.0")
        print(f"Input:  {input_json_path}")
        print(f"Output: {output_dir.resolve()}")
        print(f"Mode:   {'overwrite' if overwrite else 'skip existing'}")
        print(f"Names:  {'legacy' if legacy_filenames else 'timestamped'}")
        print(f"Count:  {len(conversations)}")

    rows: list[dict[str, Any]] = []
    saved = skipped = errors = 0

    for index, conv in enumerate(conversations, 1):
        try:
            filename = output_filename(conv, index, legacy_filenames)
            output_file = output_dir / filename

            # Validate before replacing an existing output, even with --overwrite.
            check_destination(output_file, input_json_path, overwrite=True)
            content, rendered_count = conversation_to_markdown(conv, index, options)
            try:
                write_text(output_file, content, overwrite=overwrite)
                saved += 1
            except FileExistsError:
                skipped += 1

            rows.append(
                {
                    "number": f"{index:04d}",
                    "title": conversation_title(conv, index),
                    "id": conversation_id(conv, index),
                    "created_at": conv.get("create_time") or "",
                    "updated_at": conv.get("update_time") or "",
                    "rendered_message_count": rendered_count,
                    "file": output_file.name,
                }
            )

            if not quiet and index % 50 == 0:
                print(f"  processed {index}/{len(conversations)}")
        except Exception as exc:
            errors += 1
            if not quiet:
                print(f"  error on conversation {index}: {exc}")

    write_index_csv(rows, output_dir, overwrite=overwrite)

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
        description="Convert ChatGPT export conversations.json into individual timestamped Markdown files."
    )
    parser.add_argument("-i", "--input", help="Path to ChatGPT conversations.json")
    parser.add_argument("-o", "--output", help="Output directory")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Markdown files")
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Compatibility flag. Skip existing files, now the default.",
    )
    parser.add_argument("--legacy-filenames", action="store_true", help="Use old 0001_Title.md filenames")
    parser.add_argument("--title", help="Filter conversations by title substring")
    parser.add_argument("--start-date", help="Filter by created date, YYYY-MM-DD")
    parser.add_argument("--end-date", help="Filter by created date, YYYY-MM-DD")
    parser.add_argument("--limit", type=int, help="Maximum conversations to render")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help=f"Display timezone, default {DEFAULT_TIMEZONE}")
    parser.add_argument("--skip-system", action="store_true", help="Skip system/developer messages")
    parser.add_argument("--include-tools", action="store_true", help="Include short tool/content JSON summaries")
    parser.add_argument("--include-empty", action="store_true", help="Keep messages with no visible rendered text")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.input:
        input_path = Path(args.input).expanduser()
    else:
        detected = autodetect_input(Path.cwd())
        if detected is None:
            print("Error: could not find ChatGPT conversations.json. Use -i/--input.", file=sys.stderr)
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
        include_system=not args.skip_system,
        include_tools=args.include_tools,
        include_empty_messages=args.include_empty,
        timezone_name=args.timezone,
    )

    try:
        result = process_chatgpt_export(
            input_json_path=input_path,
            output_dir=Path(args.output) if args.output else None,
            overwrite=args.overwrite and not args.no_overwrite,
            quiet=args.quiet,
            title_filter=args.title,
            start_date=start_date,
            end_date=end_date,
            limit=args.limit,
            legacy_filenames=args.legacy_filenames,
            options=options,
        )
    except (OSError, ValueError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0 if result["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
