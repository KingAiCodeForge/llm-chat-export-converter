# Version 1.1.0 review ledger

This release qualifies bounded offline conversion and output-preservation behavior
using synthetic public fixtures. It does not certify every historical ChatGPT or
Claude export schema, hostile Markdown/HTML rendering, arbitrary resource use, or
the behavior of every spreadsheet application. No private export was accessed,
copied, committed, uploaded or used for testing.

## Preserved public sources

| Source | Exact commit | Preservation |
| --- | --- | --- |
| Original public `main` | `f8ca541f2476bcaf953af17830dffd7d84f937ce` | `preserve/main-20261020`; original main checkout retained |
| PR #1, `review/csv-formula-safe-index-20261017` | `483e7b97cc84bd4bfbacf931abd3dc13446cc0c8` | `preserve/pr1-20261020`; original review branch retained; complete ancestry in integration |

The isolated integration worktree is on
`integration/portable-release-20261020`. Original refs were also saved in a
local Git bundle before edits. No original branch was deleted or force-updated.
No additional launcher/prototype variant exists in the inspected public tree;
historical source remains accessible through the preserved commit history.
The release receipt records the exact integrated source commit and SHA-256
hashes of the distributable artifacts, rather than duplicating historical code.

## Script and module ledger

| File | Inspected | Change | Executed qualification |
| --- | --- | --- | --- |
| `llm_export_cli.py` | Full dispatcher, parsers, JSON/exit contract, all subcommands | Version 1.1.0; ASCII-escaped JSON for legacy redirected Windows streams | Existing CLI suite; missing inputs, invalid filters, partial reports, fixture conversion, copy default, Unicode external paths and ASCII stdout |
| `scripts/chatgpt_export_to_markdown.py` | Complete renderer, date/filter logic, names, input discovery, CLI and writes | CSV formula guard from PR #1; sanitized ID component; protected index/input aliases; replacement avoids hardlink mutation; malformed input before mkdir; concise CLI errors; home expansion | Synthetic messages/roles/chronology; fixture conversion; formula CSV; index and hardlink alias preservation; invalid JSON; direct help/conversion outside source under spaces and non-ASCII paths |
| `scripts/claude_export_to_markdown.py` | Complete renderer, tools/thinking policy, attachment summaries, date/filter logic, names, CLI and writes | Same output protections as ChatGPT; `--include-empty` no longer reintroduces excluded thinking through fallback text | Fixture and structured-message tests; thinking/tool opt-ins; attachments; CSV formula metadata; index aliases; malformed JSON; direct external entrypoints |
| `scripts/restore_chatgpt_assets.py` | Complete name-map lookup, extension sniffing, categories, collision allocator, copies/links, CLI and CSV | Formula-safe asset CSV; copy default for direct API/CLI; exclusive copies; protected pre-existing index; input validation; closed sniff handles; control-character filenames; home expansion | Synthetic asset restore; original byte preservation after editing copies; legacy name collision; dry-run no mutation; missing folder; existing index/destination protected; direct help |
| `scripts/csv_safety.py` | Complete helper | PR #1 formula escaping extended to Unicode whitespace/BOM | Formula leaders, whitespace/BOM, ordinary text, numeric values and all three CSV call sites |
| `scripts/output_safety.py` | Complete new helper | Exclusive creation; alias/symlink checks; temporary-file replacement | Input hardlink aliases, replacement hardlink preservation, existing-copy protection, symlink checks where permitted |
| `scripts/__init__.py` | Complete one-line package marker | Unchanged | Package imports from clean installed wheel |
| `tests/test_llm_export_cli.py` | Complete existing tests | Unchanged | Complete test suite |
| `tests/test_csv_safety.py` | Complete PR #1 regressions | Preserved intact | Complete test suite |
| `tests/test_output_safety.py` | Complete new regression suite | New | Complete test suite |
| `tests/test_rendering.py` | Complete new renderer regressions | New | Complete test suite |

No executable Python file in the release is unreviewed. Inspection is not
exhaustive semantic validation: date/schema variants, attachment rendering and
extension classification remain best effort. Runtime dependencies are Python's
standard library only. Invalid or unavailable timezone data falls back to UTC.
The advanced `--hardlink` option deliberately shares file contents; copying is
the safe default. Conversion can report partial results for malformed individual
conversations and is not a transactional whole-export operation.

## Exposure and packaging review

`.gitignore`, repository-local excludes, configured global-exclude status,
tracked file inventory and final release-member lists were inspected. The only
tracked `private_exports` entry is its empty `.gitkeep`. Examples contain dummy
conversation content under the repository's MIT license. No previously ignored
source with unclear ownership was imported and no global ignore setting was
changed. Local credentials/configuration (`.env*`, `*.key`, `*.pem`) are now also
excluded. Tracked files and distributable members were checked independently of
ignore rules.

`MANIFEST.in` explicitly includes the public dummy fixtures, tests and review
documentation in the source distribution, so its tests work after extraction.
Build products, virtual environments, local receipts, original-source bundles,
export data and machine paths do not enter the wheel or source distribution.

## Reproducing bounded qualification

From a clean Python 3.10+ environment:

```sh
python -m pip install build pytest
python -m pytest -q
python -m build --outdir dist
python -m pip install --no-deps dist/llm_chat_export_converter-1.1.0-py3-none-any.whl
```

Then change to a separate directory, run `llm-chat-export capabilities`, convert
the dummy ChatGPT and Claude examples to new output paths, and run the tests with
`python -m pytest --import-mode=importlib /absolute/source/tests -q`. Verify that
the imported modules resolve inside the installed environment. The release
receipt records actual Windows/Linux commands and results. Other platforms and
real private archives were not tested.
