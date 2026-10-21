"""
Restore ChatGPT export asset blobs to useful filenames.

Official ChatGPT exports can store uploaded or generated assets as opaque
``file-*.dat`` or ``file_*.dat`` blobs. The export may also include
``conversation_asset_file_names.json``, which maps blob ids back to the
original human filenames. This script rebuilds a browsable assets tree with
real names and extensions so those files can be opened, searched, or passed to
another local converter.

No network calls. No upload. Local files only.
"""

from __future__ import annotations

import argparse
import csv
import json
import io
import os
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# The modules are usable both as package imports and standalone scripts.
try:
    from .csv_safety import spreadsheet_safe_row
    from .output_safety import check_destination, prepare_cli_streams, write_text
except ImportError:  # direct: python scripts/<converter>.py
    from csv_safety import spreadsheet_safe_row
    from output_safety import check_destination, prepare_cli_streams, write_text


BLOB_PATTERNS = ("file-*.dat", "file_*.dat")

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
    ".html",
    ".htm",
    ".md",
    ".txt",
    ".rtf",
    ".odt",
    ".ods",
    ".odp",
    ".tex",
}
DATA_EXTENSIONS = {
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".xdf",
    ".hpt",
    ".py",
    ".log",
    ".bin",
    ".ini",
    ".tsv",
    ".adx",
    ".ctz",
    ".kess3",
    ".s19",
    ".hex",
    ".asm",
    ".c",
    ".h",
    ".ipynb",
}
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".svg",
    ".heic",
}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac"}
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".tar", ".gz", ".rar"}

MAGIC_EXTENSIONS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF8", ".gif"),
    (b"RIFF", ".wav"),
    (b"%PDF-", ".pdf"),
    (b"PK\x03\x04", ".zip"),
    (b"<!DOCTYPE", ".html"),
    (b"<html", ".html"),
    (b"{", ".json"),
    (b"<?xml", ".xml"),
)


def sniff_extension(path: Path) -> str:
    """Return a best-effort extension from file magic bytes."""
    try:
        with path.open("rb") as stream:
            head = stream.read(32).lstrip()
    except OSError:
        return ".bin"

    lower_head = head.lower()
    for signature, extension in MAGIC_EXTENSIONS:
        if lower_head.startswith(signature.lower()):
            return extension
    return ".bin"


def kind_for_extension(extension: str) -> str:
    extension = extension.lower()
    if extension in IMAGE_EXTENSIONS:
        return "images"
    if extension in DOCUMENT_EXTENSIONS:
        return "documents"
    if extension in DATA_EXTENSIONS:
        return "data"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    if extension in ARCHIVE_EXTENSIONS:
        return "archives"
    return "other"


def sanitize_filename(name: str, max_stem_len: int = 110) -> str:
    """Make a Windows-safe filename while preserving the extension."""
    name = (name or "asset").replace("%27", "'")
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", name).strip().strip(".")
    stem, extension = os.path.splitext(name)
    stem = re.sub(r"\s+", " ", stem).strip()
    if len(stem) > max_stem_len:
        stem = stem[:max_stem_len].rstrip()
    return (stem or "asset") + extension


def link_or_copy(source: Path, destination: Path, copy: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        with source.open("rb") as original, destination.open("xb") as restored:
            shutil.copyfileobj(original, restored)
        return
    try:
        os.link(source, destination)
    except FileExistsError:
        raise
    except OSError:
        with source.open("rb") as original, destination.open("xb") as restored:
            shutil.copyfileobj(original, restored)


def collect_asset_blobs(source_dir: Path) -> list[Path]:
    """Find both legacy file-*.dat and newer file_*.dat ChatGPT blobs."""
    found: dict[str, Path] = {}
    for pattern in BLOB_PATTERNS:
        for path in source_dir.glob(pattern):
            # An untrusted export must not borrow bytes from an arbitrary
            # external target through a file-*.dat symbolic link.
            if path.is_symlink():
                raise ValueError(f"asset blob is a symbolic link: {path.name}")
            if path.is_file():
                found[path.name] = path
    return sorted(found.values(), key=lambda path: path.name.lower())


def normalise_asset_id(asset_id: str) -> str:
    """Use a stable file- prefix in restored names."""
    if asset_id.startswith("file_"):
        return "file-" + asset_id[5:]
    return asset_id


def asset_name_map_keys(blob: Path) -> list[str]:
    """Return possible keys used by different ChatGPT export versions."""
    stem = blob.stem
    normalised = normalise_asset_id(stem)
    alternates = [stem, normalised]
    if stem.startswith("file-"):
        alternates.append("file_" + stem[5:])
    elif stem.startswith("file_"):
        alternates.append("file-" + stem[5:])

    keys = [blob.name]
    for value in alternates:
        keys.append(value)
        keys.append(value + ".dat")

    seen: set[str] = set()
    unique: list[str] = []
    for key in keys:
        if key not in seen:
            unique.append(key)
            seen.add(key)
    return unique


def coerce_original_name(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("file_name", "filename", "name", "original_name"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def lookup_original_name(name_map: dict[str, Any], blob: Path) -> tuple[str | None, str]:
    for key in asset_name_map_keys(blob):
        original_name = coerce_original_name(name_map.get(key))
        if original_name:
            return original_name, key
    return None, ""


def load_name_map(source_dir: Path) -> dict[str, Any]:
    path = source_dir / "conversation_asset_file_names.json"
    if path.is_symlink():
        raise ValueError("conversation asset name map must not be a symbolic link")
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("conversation_asset_file_names.json should contain a JSON object")
    return data


def unique_destination(directory: Path, filename: str, used: set[Path]) -> Path:
    destination = directory / filename
    if destination not in used and not destination.exists():
        used.add(destination)
        return destination

    stem, extension = os.path.splitext(filename)
    counter = 2
    while True:
        candidate = directory / f"{stem}_{counter}{extension}"
        if candidate not in used and not candidate.exists():
            used.add(candidate)
            return candidate
        counter += 1


def restore_assets(
    source_dir: Path,
    output_dir: Path | None = None,
    copy: bool = True,
    flat: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise ValueError(f"input directory not found: {source_dir}")
    output_dir = output_dir.expanduser().resolve() if output_dir else source_dir / "assets"
    if output_dir == source_dir:
        raise ValueError("output must not be the input directory")
    index_path = output_dir / "_asset_index.csv"
    if not dry_run:
        check_destination(index_path, source_dir / "conversation_asset_file_names.json", overwrite=False)
    name_map = load_name_map(source_dir)
    blobs = collect_asset_blobs(source_dir)

    rows: list[dict[str, Any]] = []
    used_destinations: set[Path] = set()
    sniffed = 0

    for blob in blobs:
        blob_id = blob.stem
        normalised_id = normalise_asset_id(blob_id)
        original_name, map_key = lookup_original_name(name_map, blob)

        if original_name:
            restored_name = sanitize_filename(original_name)
            if not os.path.splitext(restored_name)[1]:
                restored_name += sniff_extension(blob)
                sniffed += 1
        else:
            restored_name = f"{normalised_id}{sniff_extension(blob)}"
            sniffed += 1

        extension = os.path.splitext(restored_name)[1].lower()
        kind = kind_for_extension(extension)
        target_dir = output_dir if flat else output_dir / kind
        target_name = f"{normalised_id}__{restored_name}"
        if len(target_name) > 150:
            stem, ext = os.path.splitext(target_name)
            target_name = stem[:150] + ext

        destination = unique_destination(target_dir, target_name, used_destinations)
        if not dry_run:
            link_or_copy(blob, destination, copy=copy)

        rows.append(
            {
                "dat_id": blob_id,
                "source_blob": blob.name,
                "normalised_id": normalised_id,
                "restored_path": str(destination.relative_to(output_dir)),
                "kind": kind,
                "ext": extension,
                "size_bytes": blob.stat().st_size,
                "original_name": restored_name,
                "in_name_map": bool(map_key),
                "name_map_key": map_key,
            }
        )

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        handle = io.StringIO(newline="")
        writer = csv.DictWriter(handle, fieldnames=[
            "dat_id", "restored_path", "kind", "ext", "size_bytes",
            "original_name", "in_name_map", "source_blob", "normalised_id", "name_map_key",
        ])
        writer.writeheader()
        writer.writerows(spreadsheet_safe_row(row) for row in rows)
        write_text(index_path, handle.getvalue(), overwrite=False)

    return {
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "blob_count": len(blobs),
        "name_map_count": len(name_map),
        "restored": len(rows),
        "sniffed": sniffed,
        "by_kind": dict(Counter(row["kind"] for row in rows)),
        "top_extensions": Counter(row["ext"] for row in rows).most_common(12),
        "index_path": str(index_path),
        "dry_run": dry_run,
        "copy": copy,
        "flat": flat,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restore ChatGPT export file-*.dat/file_*.dat asset blobs to real filenames."
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="ChatGPT export folder containing .dat blobs and optional conversation_asset_file_names.json",
    )
    parser.add_argument("-o", "--output", help="Output assets directory, default: <input>/assets")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--copy", dest="copy", action="store_true", help="Copy files (default)")
    mode.add_argument("--hardlink", dest="copy", action="store_false", help="Advanced: share source file contents")
    parser.set_defaults(copy=True)
    parser.add_argument("--flat", action="store_true", help="Do not sort into kind subfolders")
    parser.add_argument("--dry-run", action="store_true", help="Preview restored names without writing files")
    return parser


def main() -> int:
    prepare_cli_streams()
    parser = build_parser()
    args = parser.parse_args()

    source_dir = Path(args.input).expanduser()
    if not source_dir.exists():
        print(f"Error: input folder not found: {source_dir}", file=sys.stderr)
        return 1

    try:
        result = restore_assets(
            source_dir=source_dir,
            output_dir=Path(args.output) if args.output else None,
            copy=args.copy,
            flat=args.flat,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    mode = "dry-run" if result["dry_run"] else ("copy" if result["copy"] else "hardlink")
    print("ChatGPT Asset Restore")
    print(f"Input:   {result['source_dir']}")
    print(f"Output:  {result['output_dir']}")
    print(
        "Blobs:   "
        f"{result['blob_count']} | name-map entries: {result['name_map_count']} | mode: {mode}"
    )
    print(f"Restored: {result['restored']} | extension sniff fallback: {result['sniffed']}")
    print(f"By kind:  {result['by_kind']}")
    print(f"Top ext:  {result['top_extensions']}")
    print(f"Index:    {'not written (dry run)' if result['dry_run'] else result['index_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
