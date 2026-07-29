from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path

import pytest

import llm_export_cli as cli


REPO_ROOT = Path(__file__).resolve().parents[1]


def invoke(arguments):
    stdout = StringIO()
    stderr = StringIO()
    result = cli.run_cli(arguments, stdout=stdout, stderr=stderr)
    return result, stdout.getvalue(), stderr.getvalue()


def test_capabilities_is_json_and_read_only():
    result, stdout, stderr = invoke(["capabilities"])
    assert result == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["network_access"] is False
    assert payload["commands"]["restore-assets"]["writes_default"] is False


def test_chatgpt_fixture_converts_with_json_report(tmp_path):
    source = REPO_ROOT / "examples" / "dummy_chatgpt_conversations.json"
    output = tmp_path / "chatgpt"
    result, stdout, stderr = invoke(
        ["chatgpt", "--input", str(source), "--output", str(output)]
    )
    assert result == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["command"] == "chatgpt"
    assert payload["result"]["saved"] == 1
    assert len(list(output.glob("*.md"))) == 1
    assert (output / "_index.csv").is_file()

    index_before = (output / "_index.csv").read_bytes()
    result, second_stdout, second_stderr = invoke(
        ["chatgpt", "--input", str(source), "--output", str(output)]
    )
    assert result == cli.EXIT_USAGE
    assert second_stdout == ""
    assert json.loads(second_stderr)["error"]["code"] == "invalid_argument"
    assert (output / "_index.csv").read_bytes() == index_before


def test_claude_fixture_converts_with_json_report(tmp_path):
    source = REPO_ROOT / "examples" / "dummy_claude_conversations.json"
    output = tmp_path / "claude"
    result, stdout, stderr = invoke(
        ["claude", "--input", str(source), "--output", str(output)]
    )
    assert result == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["command"] == "claude"
    assert payload["result"]["saved"] == 1
    assert len(list(output.glob("*.md"))) == 1
    assert (output / "_index.csv").is_file()


def test_restore_assets_is_dry_run_without_execute(tmp_path):
    source = tmp_path / "export"
    source.mkdir()
    (source / "file-example.dat").write_bytes(b"example")
    output = tmp_path / "assets"
    result, stdout, stderr = invoke(
        ["restore-assets", "--input", str(source), "--output", str(output)]
    )
    assert result == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["result"]["dry_run"] is True
    assert payload["result"]["restored"] == 1
    assert not output.exists()


def test_missing_input_is_json_error(tmp_path):
    result, stdout, stderr = invoke(
        [
            "chatgpt",
            "--input",
            str(tmp_path / "missing.json"),
            "--output",
            str(tmp_path / "output"),
        ]
    )
    assert result == cli.EXIT_PROCESSING
    assert stdout == ""
    error = json.loads(stderr)["error"]
    assert error["code"] == "processing_failed"
    assert error["exception_type"] == "ValueError"


@pytest.mark.parametrize("value", ["0", "-1"])
def test_limit_must_be_positive(value):
    source = REPO_ROOT / "examples" / "dummy_chatgpt_conversations.json"
    result, stdout, stderr = invoke(
        [
            "chatgpt",
            "--input",
            str(source),
            "--output",
            "unused",
            "--limit",
            value,
        ]
    )

    assert result == cli.EXIT_USAGE
    assert stdout == ""
    assert json.loads(stderr)["error"]["code"] == "invalid_argument"


def test_inverted_date_range_is_usage_error(tmp_path):
    source = REPO_ROOT / "examples" / "dummy_chatgpt_conversations.json"
    result, stdout, stderr = invoke(
        [
            "chatgpt",
            "--input",
            str(source),
            "--output",
            str(tmp_path / "output"),
            "--start-date",
            "2030-01-01",
            "--end-date",
            "2020-01-01",
        ]
    )

    assert result == cli.EXIT_USAGE
    assert stdout == ""
    assert json.loads(stderr)["error"]["code"] == "invalid_argument"


@pytest.mark.parametrize(
    ("command", "fixture_name", "date_flag", "value"),
    [
        ("chatgpt", "dummy_chatgpt_conversations.json", "--start-date", "not-a-date"),
        ("chatgpt", "dummy_chatgpt_conversations.json", "--end-date", "2026-99-99"),
        ("claude", "dummy_claude_conversations.json", "--start-date", "not-a-date"),
        ("claude", "dummy_claude_conversations.json", "--end-date", "2026-99-99"),
    ],
)
def test_invalid_date_is_usage_error(
    tmp_path, command, fixture_name, date_flag, value
):
    source = REPO_ROOT / "examples" / fixture_name
    result, stdout, stderr = invoke(
        [
            command,
            "--input",
            str(source),
            "--output",
            str(tmp_path / "output"),
            date_flag,
            value,
        ]
    )

    assert result == cli.EXIT_USAGE
    assert stdout == ""
    error = json.loads(stderr)["error"]
    assert error["code"] == "invalid_argument"
    assert error["command"] == command
    assert "Invalid date" in error["message"]
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("module", [cli.chatgpt, cli.claude])
def test_end_date_includes_fractional_final_second(module):
    end_date = module.parse_date_filter("2026-07-22", end_of_day=True)

    assert end_date is not None
    assert (
        end_date.hour,
        end_date.minute,
        end_date.second,
        end_date.microsecond,
    ) == (23, 59, 59, 999999)


def test_restore_execute_requires_explicit_output(tmp_path):
    source = tmp_path / "export"
    source.mkdir()
    (source / "file-example.dat").write_bytes(b"example")

    result, stdout, stderr = invoke(
        ["restore-assets", "--input", str(source), "--execute"]
    )

    assert result == cli.EXIT_USAGE
    assert stdout == ""
    assert json.loads(stderr)["error"]["code"] == "invalid_argument"
    assert not (source / "assets").exists()


def test_restore_execute_copies_by_default(tmp_path):
    source = tmp_path / "export"
    source.mkdir()
    blob = source / "file-example.dat"
    blob.write_bytes(b"source")
    output = tmp_path / "assets"

    result, stdout, stderr = invoke(
        [
            "restore-assets",
            "--input",
            str(source),
            "--output",
            str(output),
            "--execute",
        ]
    )

    assert result == cli.EXIT_SUCCESS
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["result"]["copy"] is True
    restored = next(path for path in output.rglob("*") if path.is_file() and path.suffix != ".csv")
    assert not os.path.samefile(blob, restored)
    restored.write_bytes(b"changed")
    assert blob.read_bytes() == b"source"


def test_partial_conversion_has_distinct_exit_code(monkeypatch, tmp_path):
    source = REPO_ROOT / "examples" / "dummy_chatgpt_conversations.json"
    monkeypatch.setattr(
        cli.chatgpt,
        "process_chatgpt_export",
        lambda **_kwargs: {"saved": 1, "skipped": 0, "errors": 1},
    )

    result, stdout, stderr = invoke(
        ["chatgpt", "--input", str(source), "--output", str(tmp_path / "output")]
    )

    assert result == cli.EXIT_PARTIAL
    assert stderr == ""
    assert json.loads(stdout)["status"] == "partial"
