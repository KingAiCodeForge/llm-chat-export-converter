"""Prevent spreadsheet formula execution when CSV indexes are opened in Excel."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import chatgpt_export_to_markdown as chatgpt
from scripts import claude_export_to_markdown as claude
from scripts import restore_chatgpt_assets as assets
from scripts.csv_safety import spreadsheet_safe_cell, spreadsheet_safe_row


@pytest.mark.parametrize(
    "raw",
    ["=1+2", "+SUM(1,2)", "-1+2", "@SUM(1,2)",
     "  =HYPERLINK(\"x\")", "\t=1+2", "\r=1+2", "\n=1+2", "\ufeff=1+2"],
)
def test_dangerous_metadata_prefixed_with_apostrophe(raw):
    assert spreadsheet_safe_cell(raw) == "'" + raw


@pytest.mark.parametrize("raw", ["normal title", "x=y", "it's a test", "", "    "])
def test_plain_text_left_unchanged(raw):
    assert spreadsheet_safe_cell(raw) == raw


def test_numeric_index_values_remain_numeric():
    assert spreadsheet_safe_row({"number": 42, "title": "=1+2"}) == {
        "number": 42, "title": "'=1+2"
    }


@pytest.mark.parametrize(
    ("module", "row"),
    [
        (
            chatgpt,
            {
                "number": 1, "title": "=2+3", "id": "@SUM(1,2)",
                "created_at": "2026-10-17", "updated_at": "2026-10-17",
                "rendered_message_count": 1, "file": "safe.md",
            },
        ),
        (
            claude,
            {
                "number": 1, "title": "+2+3", "uuid": "-cmd",
                "created_at": "2026-10-17", "updated_at": "2026-10-17",
                "message_count": 1, "rendered_message_count": 1, "file": "safe.md",
            },
        ),
    ],
)
def test_conversation_index_writes_formula_safe_cells(tmp_path, module, row):
    module.write_index_csv([row], tmp_path)
    with (tmp_path / "_index.csv").open(newline="", encoding="utf-8") as stream:
        result = next(csv.DictReader(stream))
    assert result["title"].startswith("'")
    identity = result.get("uuid", result.get("id"))
    assert identity.startswith("'")
    assert result["number"] == "1"


def test_restore_asset_index_writes_formula_safe_original_name(tmp_path):
    source = tmp_path / "export"
    source.mkdir()
    (source / "file-abc.dat").write_bytes(b"not a real asset")
    (source / "conversation_asset_file_names.json").write_text(
        json.dumps({"file-abc": "=1+2.txt"}), encoding="utf-8"
    )
    output = tmp_path / "assets"
    result = assets.restore_assets(
        source_dir=source, output_dir=output, copy=True, dry_run=False
    )
    assert result["restored"] == 1
    with (output / "_asset_index.csv").open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["original_name"] == "'=1+2.txt"


@pytest.mark.parametrize(
    "script",
    ["chatgpt_export_to_markdown.py", "claude_export_to_markdown.py",
     "restore_chatgpt_assets.py"],
)
def test_direct_script_entrypoint_imports_csv_helper(script):
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / script), "--help"],
        cwd=root, capture_output=True, text=True, timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
