# LLM and automation interface

`llm-chat-export` is an offline, JSON-first dispatcher for the public conversion functions in this repository.

```bash
python -m pip install -e .
llm-chat-export capabilities
llm-chat-export --help
```

Convert an explicit ChatGPT export:

```bash
llm-chat-export chatgpt \
  --input ./private_exports/chatgpt/conversations.json \
  --output ./outputs/chatgpt_markdown
```

Convert an explicit Claude export:

```bash
llm-chat-export claude \
  --input ./private_exports/claude/conversations.json \
  --output ./outputs/claude_markdown
```

Inspect asset restoration without writing:

```bash
llm-chat-export restore-assets \
  --input ./private_exports/chatgpt \
  --output ./outputs/chatgpt_assets
```

Add `--execute` only after reviewing the dry-run JSON. An explicit `--output` is mandatory for execution. Restoration copies by default; use `--hardlink` only when shared-file semantics are intentional and understood.

Successful commands emit one schema `1.0` JSON object to stdout. Partial conversions emit their JSON report and return 1. Parser/usage errors return 2. Fatal processing failures emit one JSON error to stderr and return 3. Conversion never overwrites existing Markdown unless `--overwrite` is present. A pre-existing `_index.csv` also requires `--overwrite` or a new output directory. `--limit` must be at least 1, and a start date must not be later than the end date.

Raw exports are private input. Never place them in prompts, logs, commits, fixtures, or public issue reports.
