# LLM Chat Export Converter

Local/offline Python scripts for converting ChatGPT and Claude exports into neat timestamped Markdown conversations plus searchable `_index.csv` files.

The goal is simple: keep raw exports private, make the output easier to search, sort and feed into local LLM workflows.

## Features

- Converts ChatGPT `conversations.json` into one Markdown file per conversation.
- Converts Claude `conversations.json` export batches into one Markdown file per conversation.
- Restores ChatGPT `file-*.dat` and `file_*.dat` asset blobs to real filenames when `conversation_asset_file_names.json` is present.
- Adds timestamped filenames.
- Writes `_index.csv` for sorting and filtering.
- Uses ASCII-safe Windows-friendly filenames.
- Skips tool/thinking payloads by default.
- Runs locally with no network calls and no upload.

## Install

Python 3.10+ is recommended.

No third-party packages are required.

```powershell
python --version
```

## Safe Folder Layout

Put raw exports in `private_exports/`. That folder is ignored by Git.

Example:

```text
private_exports/
  chatgpt/conversations.json
  chatgpt/conversation_asset_file_names.json
  chatgpt/file-abc123.dat
  claude/conversations.json
outputs/
  chatgpt_markdown/
  claude_markdown/
  chatgpt_assets/
```

Do not commit raw exports. They can contain private chats, names, emails, files, memories, prompts and sensitive context.

## ChatGPT Usage

```powershell
python .\scripts\chatgpt_export_to_markdown.py `
  --input .\private_exports\chatgpt\conversations.json `
  --output .\outputs\chatgpt_markdown
```

Optional:

```powershell
python .\scripts\chatgpt_export_to_markdown.py `
  --input .\private_exports\chatgpt\conversations.json `
  --output .\outputs\chatgpt_markdown `
  --timezone Australia/Adelaide `
  --skip-system `
  --overwrite
```

## ChatGPT Asset Usage

ChatGPT exports may store uploads and generated files as opaque `.dat` blobs. If the export includes `conversation_asset_file_names.json`, restore those blobs before trying to inspect or convert them.

```powershell
python .\scripts\restore_chatgpt_assets.py `
  --input .\private_exports\chatgpt `
  --output .\outputs\chatgpt_assets
```

Preview first:

```powershell
python .\scripts\restore_chatgpt_assets.py `
  --input .\private_exports\chatgpt `
  --dry-run
```

By default the script hardlinks files to avoid duplicating large exports on the same drive. Use `--copy` if you need separate physical copies. Output is sorted into `images/`, `documents/`, `data/`, `audio/`, `archives/`, and `other/`, plus `_asset_index.csv`.

## Claude Usage

```powershell
python .\scripts\claude_export_to_markdown.py `
  --input .\private_exports\claude\conversations.json `
  --output .\outputs\claude_markdown
```

Optional:

```powershell
python .\scripts\claude_export_to_markdown.py `
  --input .\private_exports\claude\conversations.json `
  --output .\outputs\claude_markdown `
  --timezone Australia/Adelaide `
  --overwrite
```

## Privacy Checklist Before Publishing

- `private_exports/` is empty or contains only `.gitkeep`.
- `outputs/` is not committed.
- No real `conversations.json`, `memories.json`, `users.json`, attachments or mined notes are committed.
- No export sidecars such as `user.json`, `group_chats.json`, `message_feedback.json`, `shared_conversations.json`, `shopping.json`, `sora.json`, or `export_manifest.json` are committed.
- No `file-*.dat`, `file_*.dat`, `conversation_asset_file_names.json`, `chat.html`, `latest_export/`, split-output folders, or restored `assets/` folders are committed.
- Example files use dummy text only.
- No personal names, emails, company strategy, client material or private prompts are present.

## Suggested Repo Name

Recommended public name:

```text
llm-chat-export-converter
```

Reason: neutral, clear and useful to people who only want a generic export converter.

Avoid putting a private company or project name in the public utility unless the goal is branding instead of generic reuse.
