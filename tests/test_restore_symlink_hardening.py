"""Synthetic, offline privacy tests for asset restore source handling."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import restore_chatgpt_assets as assets


def try_link(link: Path, destination: Path) -> None:
    try:
        link.symlink_to(destination)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")


@pytest.mark.parametrize("dry_run", [True, False])
def test_external_asset_symlink_is_rejected_before_output(tmp_path, dry_run):
    source = tmp_path / "export"
    source.mkdir()
    secret = tmp_path / "outside_private_input.txt"
    secret.write_text("sensitive contents must stay outside the restore", encoding="utf-8")
    link = source / "file-external.dat"
    try_link(link, secret)
    output = tmp_path / "output"

    with pytest.raises(ValueError, match="asset blob is a symbolic link"):
        assets.restore_assets(source, output, dry_run=dry_run)

    assert secret.read_text(encoding="utf-8").startswith("sensitive contents")
    assert not output.exists()


def test_external_asset_name_map_symlink_is_rejected(tmp_path):
    source = tmp_path / "export"
    source.mkdir()
    (source / "file-regular.dat").write_bytes(b"ordinary")
    external_map = tmp_path / "outside_map.json"
    external_map.write_text(json.dumps({"file-regular": {"name": "secret.txt"}}), encoding="utf-8")
    try_link(source / "conversation_asset_file_names.json", external_map)
    output = tmp_path / "output"

    with pytest.raises(ValueError, match="name map must not be a symbolic link"):
        assets.restore_assets(source, output)

    assert not output.exists()
    assert external_map.read_text(encoding="utf-8").startswith("{")


def test_normal_asset_and_normal_name_map_still_restore(tmp_path):
    source = tmp_path / "export"
    source.mkdir()
    original = source / "file-regular.dat"
    original.write_bytes(b"ordinary")
    (source / "conversation_asset_file_names.json").write_text(
        json.dumps({"file-regular": {"name": "report.txt"}}), encoding="utf-8",
    )
    output = tmp_path / "output"
    preview = assets.restore_assets(source, output, dry_run=True)
    assert preview["restored"] == 1
    assert not output.exists()

    result = assets.restore_assets(source, output)
    assert result["restored"] == 1
    restored = list(output.rglob("*.txt"))
    assert len(restored) == 1
    assert restored[0].read_bytes() == b"ordinary"
    assert original.read_bytes() == b"ordinary"
    assert (output / "_asset_index.csv").is_file()
