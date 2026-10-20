"""Core rendering promises using synthetic messages only."""
from __future__ import annotations

from scripts import chatgpt_export_to_markdown as chatgpt
from scripts import claude_export_to_markdown as claude
from scripts import restore_chatgpt_assets as assets


def test_chatgpt_roles_tools_and_chronology():
    conversation = {"mapping": {}}
    for key, role, timestamp in [("b", "assistant", 20), ("a", "human", 10), ("c", "tool", 30), ("d", "system", 5)]:
        conversation["mapping"][key] = {"message": {"author": {"role": role},
            "create_time": timestamp, "content": {"parts": [key]}}}
    messages = chatgpt.extract_messages(conversation, chatgpt.RenderOptions(include_system=False))
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert [message["content"] for message in messages] == ["a", "b"]
    messages = chatgpt.extract_messages(conversation, chatgpt.RenderOptions(include_tools=True))
    assert [message["content"] for message in messages] == ["d", "a", "b", "c"]


def test_claude_include_empty_does_not_reintroduce_thinking_fallback():
    message = {"content": [{"type": "thinking", "thinking": "synthetic hidden text"}],
               "text": "synthetic hidden text"}
    assert claude.extract_text_blocks(message, claude.RenderOptions()) == []
    assert claude.extract_text_blocks(message, claude.RenderOptions(include_empty_messages=True)) == []
    assert "synthetic hidden text" in claude.extract_text_blocks(
        message, claude.RenderOptions(include_thinking=True))[0]


def test_claude_visible_text_attachments_and_tool_opt_in():
    conversation = {"uuid": "dummy", "chat_messages": [{"sender": "human", "text": "visible",
        "attachments": [{"file_name": "dummy.txt", "mime_type": "text/plain"}]}]}
    markdown, count = claude.conversation_to_markdown(conversation, 1, claude.RenderOptions())
    assert count == 1
    assert "visible" in markdown
    assert "dummy.txt (text/plain)" in markdown
    tool = {"content": [{"type": "tool_result", "content": "synthetic result"}]}
    assert claude.extract_text_blocks(tool, claude.RenderOptions()) == []
    assert "synthetic result" in claude.extract_text_blocks(tool, claude.RenderOptions(include_tools=True))[0]


def test_asset_legacy_names_collision_and_dry_run_preservation(tmp_path):
    source = tmp_path / "archive"
    source.mkdir()
    (source / "file-dummy.dat").write_bytes(b"dummy")
    (source / "file_dummy.dat").write_bytes(b"dummy2")
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    output = tmp_path / "out"
    result = assets.restore_assets(source, output, dry_run=True)
    assert result["restored"] == 2
    assert not output.exists()
    assets.restore_assets(source, output)
    restored = list(output.rglob("*.bin"))
    assert len(restored) == 2
    assert len({path.name for path in restored}) == 2
    assert before == {path.name: path.read_bytes() for path in source.iterdir()}
