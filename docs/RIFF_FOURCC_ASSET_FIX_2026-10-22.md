# ChatGPT asset restoration — RIFF format identification fix

**Date:** 2026-10-22 06:54 ACDT · **Status:** isolated code review, not merged.

The original `scripts/restore_chatgpt_assets.py` identified every blob beginning with the four bytes `RIFF` as WAV audio. RIFF is a *container family*, also used by WebP images (`RIFF....WEBP`) and AVI (`RIFF....AVI `). An exported `file-*.dat` containing WebP was therefore restored with a misleading `.wav` suffix, sent into the audio folder and potentially treated as corrupt audio by downstream programs.

## Fix

- Read the subtype / FOURCC from header bytes 8–11.
- `RIFF....WAVE` -> `.wav`, routed as audio.
- `RIFF....WEBP` -> `.webp`, routed as images.
- Unknown/truncated RIFF -> `.bin`, routed to other, without inventing a format.
- Preserve existing PNG/JPEG/GIF/PDF/ZIP/HTML/XML/JSON sniff rules and read-only input behaviour.

## Verification

A pre-patch Python reproduction classified synthetic WebP, WAV, and AVI all as `.wav` (confirmed incorrect). The patched function passed **6/6** local Python `pytest` cases using fabricated RIFF/PDF/GIF byte headers. The repository adds `tests/test_riff_signatures.py` for direct real-module tests, including a synthetic `restore_assets` integration confirming restored WebP appears under `images`, WAV under `audio`, and unknown RIFF under `other`.

The complete repository tests were **not** run in this session, because the private repo was inspected and edited through the GitHub connector rather than a checked-out Python package. Run:

```sh
python -m pytest -q tests/test_riff_signatures.py
python -m pytest -q
```

No real/private ChatGPT export was read or uploaded; the module does not connect to a network. No historic converted files were rewritten.

Baseline blob: `7b603e439b2277115c313de14cc39928047084b2`. Candidate blob: `28ec3ce3434c2332372efb71f2baf30f50b17252`.
