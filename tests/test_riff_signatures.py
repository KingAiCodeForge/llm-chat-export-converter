"""RIFF container signature regressions: unknown RIFF must not become WAV."""
from __future__ import annotations

from scripts.restore_chatgpt_assets import (
    kind_for_extension,
    restore_assets,
    sniff_extension,
)


def test_riff_subtype_detection_not_generic_wav(tmp_path):
    blob = tmp_path / "file-format.dat"
    cases = {
        "WAVE": (b"RIFF\x18\x00\x00\x00WAVEfmt ", ".wav"),
        "WEBP": (b"RIFF\x18\x00\x00\x00WEBPVP8 ", ".webp"),
        "AVI": (b"RIFF\x18\x00\x00\x00AVI ", ".bin"),
        "TRUNCATED": (b"RIFF\x18\x00", ".bin"),
    }
    for label, (raw, expected) in cases.items():
        blob.write_bytes(raw)
        assert sniff_extension(blob) == expected, label
    assert kind_for_extension(".webp") == "images"
    assert kind_for_extension(".wav") == "audio"


def test_unknown_riff_keeps_unknown_kind_without_fabricating_audio(tmp_path):
    source = tmp_path / "export"
    source.mkdir()
    (source / "file-unknown.dat").write_bytes(b"RIFF\x18\x00\x00\x00AVI ")
    (source / "file-actual-wave.dat").write_bytes(b"RIFF\x18\x00\x00\x00WAVEfmt ")
    (source / "file-real-webp.dat").write_bytes(b"RIFF\x18\x00\x00\x00WEBPVP8 ")
    out = tmp_path / "restored"
    result = restore_assets(source, out)
    assert result["restored"] == 3
    assert len(list((out / "images").glob("*.webp"))) == 1
    assert len(list((out / "audio").glob("*.wav"))) == 1
    assert len(list((out / "other").glob("*.bin"))) == 1
    assert not list((out / "audio").glob("*unknown*"))
    # Original export blobs are never edited.
    assert (source / "file-unknown.dat").read_bytes() == b"RIFF\x18\x00\x00\x00AVI "
