from Arkcode.context.prompts import (
    build_summary_prompt,
    extract_summary,
    serialize_conversation,
)
from Arkcode.llm import Message, ToolCall, ToolResult


def test_summary_prompt_requires_two_phases_and_nine_sections() -> None:
    prompt = build_summary_prompt([Message(role="user", content="hello")])

    assert len(prompt) == 1
    assert prompt[0].role == "user"
    assert "<analysis>" in prompt[0].content
    assert "<summary>" in prompt[0].content
    assert "不要调用任何工具" in prompt[0].content
    for number in range(1, 10):
        assert f"## {number} " in prompt[0].content


def test_serialize_conversation_keeps_messages_and_tool_details() -> None:
    messages = [
        Message(role="user", content="read it"),
        Message(
            role="assistant",
            content="reading",
            tool_calls=[ToolCall("call-1", "read_file", '{"path":"a.py"}')],
        ),
        Message(
            role="tool",
            tool_results=[ToolResult("call-1", "contents", False)],
        ),
    ]

    first = serialize_conversation(messages)

    assert first == serialize_conversation(messages)
    assert "user: read it" in first
    assert "[call read_file id=call-1" in first
    assert "[result id=call-1 is_error=False] contents" in first


def test_extract_summary_uses_last_complete_summary_or_raw_fallback() -> None:
    raw = "<summary>old</summary>x<summary>new</summary>"

    assert extract_summary(raw) == "new"
    assert extract_summary("plain") == "plain"
