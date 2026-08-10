import math

from Arkcode.context.tokens import estimate_tokens, message_chars, usage_anchor
from Arkcode.llm import Message, StreamEnd, ToolCall, ToolResult


def test_estimate_tokens_uses_anchor_only_for_messages_after_anchor() -> None:
    messages = [
        Message(role="user", content="old"),
        Message(role="user", content="x" * 350),
    ]

    assert estimate_tokens(1000, messages, 1) == 1100


def test_message_chars_counts_utf8_and_tool_payloads() -> None:
    messages = [
        Message(
            role="assistant",
            content="中",
            tool_calls=[ToolCall("id", "read_file", '{"path":"a"}')],
        ),
        Message(
            role="tool",
            tool_results=[ToolResult("id", "结果")],
        ),
    ]

    expected = len("中".encode()) + len(b'{"path":"a"}') + len("结果".encode())
    assert message_chars(messages) == expected
    assert estimate_tokens(0, messages, 0) == math.ceil(expected / 3.5)


def test_usage_anchor_sums_main_stream_usage_fields() -> None:
    usage = StreamEnd(
        "stop",
        input_tokens=100,
        output_tokens=20,
        cache_read=30,
        cache_write=40,
    )

    assert usage_anchor(usage) == 190
