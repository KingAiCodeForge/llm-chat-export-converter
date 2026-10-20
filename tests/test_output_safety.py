"""Regression coverage for archive preservation and portable direct entrypoints."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import chatgpt_export_to_markdown as chatgpt
from scripts import claude_export_to_markdown as claude
from scripts import restore_chatgpt_assets as assets
from scripts.csv_safety import spreadsheet_safe_cell
from scripts.output_safety import check_destination, write_text

ROOT = Path(__file__).resolve().parents[1]
CONVERTERS = [(chatgpt, "chatgpt"), (claude, "claude")]


@pytest.mark.parametrize("prefix", ["\v", "\f", "\u00a0", "\u2003", "\ufeff \t"])
def test_formula_after_ignorable_unicode_whitespace(prefix):
    assert spreadsheet_safe_cell(prefix + "=1+2") == "'" + prefix + "=1+2"


@pytest.mark.parametrize("module,kind", CONVERTERS)
def test_invalid_json_does_not_create_output(tmp_path, module, kind):
    source = tmp_path / "broken.json"
    source.write_text("{", encoding="utf-8")
    output = tmp_path / "out"
    with pytest.raises(ValueError):
        getattr(module, f"process_{kind}_export")(source, output, quiet=True)
    assert not output.exists()
    assert source.read_text() == "{"


@pytest.mark.parametrize("module,kind", CONVERTERS)
def test_direct_function_preserves_existing_index(tmp_path, module, kind):
    source = ROOT / "examples" / f"dummy_{kind}_conversations.json"
    output = tmp_path / "out"
    output.mkdir()
    (output / "_index.csv").write_bytes(b"original index")
    with pytest.raises(FileExistsError):
        getattr(module, f"process_{kind}_export")(source, output, quiet=True)
    assert list(output.iterdir()) == [output / "_index.csv"]
    assert (output / "_index.csv").read_bytes() == b"original index"


@pytest.mark.parametrize("module,kind", CONVERTERS)
def test_input_hardlinked_to_index_never_overwritten(tmp_path, module, kind):
    source = tmp_path / "source.json"
    source.write_bytes((ROOT / "examples" / f"dummy_{kind}_conversations.json").read_bytes())
    before = source.read_bytes()
    output = tmp_path / "out"
    output.mkdir()
    os.link(source, output / "_index.csv")
    with pytest.raises(ValueError, match="aliases original"):
        getattr(module, f"process_{kind}_export")(source, output, overwrite=True, quiet=True)
    assert source.read_bytes() == before


def test_overwrite_replaces_destination_without_modifying_linked_archive(tmp_path):
    source = tmp_path / "archive.json"
    source.write_bytes(b"private original")
    output = tmp_path / "derived.md"
    os.link(source, output)
    write_text(output, "derived", overwrite=True)
    assert source.read_bytes() == b"private original"
    assert output.read_text() == "derived"
    assert not output.samefile(source)


@pytest.mark.parametrize("module,kind,id_key", [(chatgpt, "chatgpt", "id"), (claude, "claude", "uuid")])
def test_untrusted_id_cannot_create_nested_output_paths(tmp_path, module, kind, id_key):
    data = json.loads((ROOT / "examples" / f"dummy_{kind}_conversations.json").read_text())
    data[0][id_key] = "../a/b\\c"
    source = tmp_path / "source.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "out"
    result = getattr(module, f"process_{kind}_export")(source, output, quiet=True)
    assert result["errors"] == 0
    assert result["saved"] == 1
    assert len(list(output.glob("*.md"))) == 1
    assert not any(p.is_dir() for p in output.iterdir())


def test_restoration_preserves_existing_index_and_blobs(tmp_path):
    source = tmp_path / "archive"
    source.mkdir()
    blob = source / "file-dummy.dat"
    blob.write_bytes(b"original")
    output = tmp_path / "assets"
    output.mkdir()
    (output / "_asset_index.csv").write_bytes(b"old index")
    with pytest.raises(FileExistsError):
        assets.restore_assets(source, output)
    assert blob.read_bytes() == b"original"
    assert (output / "_asset_index.csv").read_bytes() == b"old index"
    assert len(list(output.iterdir())) == 1


def test_direct_restoration_copies_by_default(tmp_path):
    source = tmp_path / "archive"
    source.mkdir()
    blob = source / "file-dummy.dat"
    blob.write_bytes(b"original")
    output = tmp_path / "out"
    assets.restore_assets(source, output)
    restored = next(output.rglob("*.bin"))
    restored.write_bytes(b"modified")
    assert blob.read_bytes() == b"original"


@pytest.mark.parametrize("module,kind", CONVERTERS)
def test_direct_entrypoint_outside_checkout_spaces_unicode(tmp_path, module, kind):
    external = tmp_path / "outside source café 空間"
    external.mkdir()
    source = external / "dummy input.json"
    source.write_bytes((ROOT / "examples" / f"dummy_{kind}_conversations.json").read_bytes())
    before = source.read_bytes()
    output = external / "derived output"
    run = subprocess.run([sys.executable, str(Path(module.__file__)), "--input", str(source),
                          "--output", str(output)], cwd=external,
                         env=dict(os.environ, PYTHONIOENCODING="ascii"),
                         capture_output=True, timeout=20)
    assert run.returncode == 0, run.stderr
    assert source.read_bytes() == before
    assert len(list(output.glob("*.md"))) == 1


@pytest.mark.parametrize("module,kind", CONVERTERS)
def test_direct_cli_invalid_json_is_concise_and_read_only(tmp_path, module, kind):
    source = tmp_path / "invalid.json"
    source.write_text("{", encoding="utf-8")
    output = tmp_path / "out"
    run = subprocess.run([sys.executable, str(Path(module.__file__)), "--input", str(source),
                          "--output", str(output)], cwd=tmp_path,
                         capture_output=True, timeout=20)
    assert run.returncode == 1
    assert b"Error:" in run.stderr
    assert b"Traceback" not in run.stderr
    assert not output.exists()


def test_missing_asset_directory_does_not_create_output(tmp_path):
    with pytest.raises(ValueError, match="input directory not found"):
        assets.restore_assets(tmp_path / "missing", tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_dispatcher_unicode_paths_with_legacy_stdout_encoding(tmp_path):
    external = tmp_path / "outside café 空間"
    external.mkdir()
    output = external / "out"
    environment = dict(os.environ, PYTHONIOENCODING="ascii")
    source = ROOT / "examples" / "dummy_chatgpt_conversations.json"
    run = subprocess.run([sys.executable, str(ROOT / "llm_export_cli.py"), "chatgpt",
                          "--input", str(source), "--output", str(output)],
                         cwd=external, env=environment, capture_output=True, timeout=20)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["result"]["output_dir"] == str(output.resolve())


def test_copy_refuses_existing_destination_instead_of_overwriting(tmp_path):
    source = tmp_path / "source.dat"
    source.write_bytes(b"original")
    destination = tmp_path / "existing.dat"
    destination.write_bytes(b"keep this")
    with pytest.raises(FileExistsError):
        assets.link_or_copy(source, destination, copy=True)
    assert destination.read_bytes() == b"keep this"


def test_symbolic_link_destination_is_rejected(tmp_path):
    source = tmp_path / "input.json"
    source.write_bytes(b"original")
    link = tmp_path / "derived.md"
    try:
        link.symlink_to(source)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")
    with pytest.raises(ValueError):
        check_destination(link, source, overwrite=True)
    assert source.read_bytes() == b"original"


def test_asset_direct_cli_external_unicode_paths_and_legacy_encoding(tmp_path):
    external = tmp_path / "external café 空間"
    external.mkdir()
    source = external / "archive"
    source.mkdir()
    blob = source / "file-dummy.dat"
    blob.write_bytes(b"original")
    output = external / "derived output 空間"
    command = [sys.executable, str(Path(assets.__file__)), "--input", str(source), "--output", str(output)]
    environment = dict(os.environ, PYTHONIOENCODING="ascii")
    preview = subprocess.run(command + ["--dry-run"], cwd=external, env=environment,
                             capture_output=True, timeout=20)
    assert preview.returncode == 0, preview.stderr
    assert not output.exists()
    run = subprocess.run(command, cwd=external, env=environment, capture_output=True, timeout=20)
    assert run.returncode == 0, run.stderr
    next(output.rglob("*.bin")).write_bytes(b"edited derived copy")
    assert blob.read_bytes() == b"original"
