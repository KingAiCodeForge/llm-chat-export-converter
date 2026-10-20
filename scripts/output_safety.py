"""Shared output checks; original exports are always read-only inputs."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def prepare_cli_streams() -> None:
    """Human-readable CLI paths must survive legacy redirected encodings."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")


def check_destination(path: Path, source: Path, *, overwrite: bool) -> None:
    if path.resolve() == source.resolve() or (
        path.exists() and source.exists() and path.samefile(source)
    ):
        raise ValueError(f"output aliases original input: {path}")
    if path.is_symlink():
        raise ValueError(f"output must not be a symbolic link: {path}")
    if path.exists() and not path.is_file():
        raise ValueError(f"output is not a regular file: {path}")
    if path.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {path}; choose a new directory or --overwrite")


def write_text(path: Path, content: str, *, overwrite: bool) -> None:
    """Exclusive creation by default; replacement never follows file hardlinks."""
    if not overwrite:
        with path.open("x", encoding="utf-8", newline="") as stream:
            stream.write(content)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".llm-export-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
