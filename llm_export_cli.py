#!/usr/bin/env python3
"""Unified, JSON-first interface for ChatGPT and Claude export tools."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

from scripts import chatgpt_export_to_markdown as chatgpt
from scripts import claude_export_to_markdown as claude
from scripts import restore_chatgpt_assets as assets


__version__ = "1.0.0"
SCHEMA_VERSION = "1.0"
EXIT_SUCCESS = 0
EXIT_PARTIAL = 1
EXIT_USAGE = 2
EXIT_PROCESSING = 3


class CliUsageError(ValueError):
    """Raised for syntax or cross-argument validation failures."""


class JsonArgumentParser(argparse.ArgumentParser):
    """Route argparse failures through the JSON error contract."""

    def error(self, message: str) -> None:
        raise CliUsageError(message)


def _emit(stream: TextIO, payload: dict[str, Any]) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _result(command: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": "llm-chat-export-converter", "version": __version__},
        "command": command,
        "status": "ok" if int(result.get("errors", 0)) == 0 else "partial",
        "result": result,
    }


def _require_file(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_file():
        raise ValueError(f"input file not found: {path}")
    return path


def _require_directory(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_dir():
        raise ValueError(f"input directory not found: {path}")
    return path


def _conversion_output(path: Path, overwrite: bool) -> Path:
    output_dir = path.expanduser()
    index_path = output_dir / "_index.csv"
    if index_path.exists() and not overwrite:
        raise CliUsageError(
            f"output index already exists: {index_path}; use --overwrite or a new output directory"
        )
    return output_dir


def _date_range(module: Any, args: argparse.Namespace) -> tuple[Any, Any]:
    try:
        start_date = module.parse_date_filter(args.start_date)
        end_date = module.parse_date_filter(args.end_date, end_of_day=True)
    except ValueError as exc:
        raise CliUsageError(str(exc)) from exc
    if start_date is not None and end_date is not None and start_date > end_date:
        raise CliUsageError("--start-date must be on or before --end-date")
    return start_date, end_date


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _run_chatgpt(args: argparse.Namespace) -> dict[str, Any]:
    start_date, end_date = _date_range(chatgpt, args)
    options = chatgpt.RenderOptions(
        include_system=not args.skip_system,
        include_tools=args.include_tools,
        include_empty_messages=args.include_empty,
        timezone_name=args.timezone,
    )
    result = chatgpt.process_chatgpt_export(
        input_json_path=_require_file(args.input),
        output_dir=_conversion_output(args.output, args.overwrite),
        overwrite=args.overwrite,
        quiet=True,
        title_filter=args.title,
        start_date=start_date,
        end_date=end_date,
        limit=args.limit,
        legacy_filenames=args.legacy_filenames,
        options=options,
    )
    return _result("chatgpt", result)


def _run_claude(args: argparse.Namespace) -> dict[str, Any]:
    start_date, end_date = _date_range(claude, args)
    options = claude.RenderOptions(
        include_thinking=args.include_thinking,
        include_tools=args.include_tools,
        include_empty_messages=args.include_empty,
        timezone_name=args.timezone,
    )
    result = claude.process_claude_export(
        input_json_path=_require_file(args.input),
        output_dir=_conversion_output(args.output, args.overwrite),
        overwrite=args.overwrite,
        quiet=True,
        title_filter=args.title,
        start_date=start_date,
        end_date=end_date,
        limit=args.limit,
        options=options,
    )
    return _result("claude", result)


def _run_restore(args: argparse.Namespace) -> dict[str, Any]:
    if args.execute and args.output is None:
        raise CliUsageError("--output is required with --execute")

    source_dir = _require_directory(args.input).resolve()
    output_dir = args.output.expanduser().resolve() if args.output else None
    if args.execute and output_dir == source_dir:
        raise CliUsageError("--output must not be the input directory")

    result = assets.restore_assets(
        source_dir=source_dir,
        output_dir=output_dir,
        copy=args.copy,
        flat=args.flat,
        dry_run=not args.execute,
    )
    return _result("restore-assets", result)


def capabilities() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": "llm-chat-export-converter", "version": __version__},
        "network_access": False,
        "stdout": "one JSON object",
        "stderr": "one JSON error object on failure",
        "commands": {
            "chatgpt": {
                "writes": "Markdown files and _index.csv",
                "overwrite_default": False,
            },
            "claude": {
                "writes": "Markdown files and _index.csv",
                "overwrite_default": False,
            },
            "restore-assets": {
                "writes_default": False,
                "execution_gate": "--execute",
                "explicit_output_required_for_execute": True,
                "write_mode_default": "copy",
                "hardlink_opt_in": "--hardlink",
            },
            "capabilities": {"writes": False},
        },
    }


def _add_common_conversion_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--title", help="case-insensitive title substring")
    parser.add_argument("--start-date", help="created on/after YYYY-MM-DD")
    parser.add_argument("--end-date", help="created on/before YYYY-MM-DD")
    parser.add_argument("--limit", type=_positive_int)
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--include-tools", action="store_true")
    parser.add_argument("--include-empty", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="llm-chat-export",
        description="Offline, JSON-first ChatGPT and Claude export converter.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    cap = subparsers.add_parser("capabilities", help="print the machine-readable interface")
    cap.set_defaults(handler=lambda _args: capabilities())

    chat = subparsers.add_parser("chatgpt", help="convert ChatGPT conversations.json")
    _add_common_conversion_flags(chat)
    chat.add_argument("--skip-system", action="store_true")
    chat.add_argument("--legacy-filenames", action="store_true")
    chat.set_defaults(handler=_run_chatgpt)

    claude_parser = subparsers.add_parser("claude", help="convert Claude conversations.json")
    _add_common_conversion_flags(claude_parser)
    claude_parser.add_argument("--include-thinking", action="store_true")
    claude_parser.set_defaults(handler=_run_claude)

    restore = subparsers.add_parser("restore-assets", help="inspect or restore ChatGPT .dat assets")
    restore.add_argument("--input", type=Path, required=True)
    restore.add_argument("--output", type=Path)
    link_mode = restore.add_mutually_exclusive_group()
    link_mode.add_argument(
        "--copy",
        dest="copy",
        action="store_true",
        help="copy restored files (default)",
    )
    link_mode.add_argument(
        "--hardlink",
        dest="copy",
        action="store_false",
        help="hardlink restored files to source blobs (advanced)",
    )
    restore.add_argument("--flat", action="store_true")
    restore.add_argument(
        "--execute",
        action="store_true",
        help="perform writes; without this flag the command is a dry run",
    )
    restore.set_defaults(handler=_run_restore, copy=True)
    return parser


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args: argparse.Namespace | None = None
    try:
        args = build_parser().parse_args(argv)
        payload = args.handler(args)
    except CliUsageError as exc:
        error: dict[str, Any] = {
            "code": "invalid_argument",
            "message": str(exc),
        }
        if args is not None and args.command is not None:
            error["command"] = args.command
        _emit(stderr, {"error": error})
        return EXIT_USAGE
    except Exception as exc:
        _emit(
            stderr,
            {
                "error": {
                    "code": "processing_failed",
                    "command": args.command if args is not None else None,
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                }
            },
        )
        return EXIT_PROCESSING
    _emit(stdout, payload)
    return EXIT_SUCCESS if payload.get("status", "ok") == "ok" else EXIT_PARTIAL


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
