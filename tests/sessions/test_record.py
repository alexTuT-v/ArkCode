"""格式 v2 会话记录编解码测试。"""

import json

import pytest

from Arkcode.llm import Message, ToolCall, ToolResult
from Arkcode.sessions.record import (
    CompactBoundary,
    decode_record,
    encode_boundary,
    encode_message,
)


def test_message_codec_omits_empty_and_default_fields() -> None:
    encoded = encode_message(Message(role="user", content="你好"), timestamp=10)

    assert json.loads(encoded) == {"role": "user", "content": "你好", "ts": 10}


def test_tool_call_arguments_are_json_objects_on_disk() -> None:
    message = Message(
        role="assistant",
        tool_calls=[ToolCall("c1", "read_file", '{"path":"a.txt"}')],
    )

    value = json.loads(encode_message(message, timestamp=11))

    assert value["tool_calls"] == [
        {"id": "c1", "name": "read_file", "arguments": {"path": "a.txt"}}
    ]
    assert decode_record(encode_message(message, timestamp=11)) == message


def test_success_result_omits_is_error() -> None:
    message = Message(role="tool", tool_results=[ToolResult("c1", "done")])

    value = json.loads(encode_message(message, timestamp=12))

    assert "is_error" not in value["tool_results"][0]


def test_error_result_preserves_is_error_true() -> None:
    message = Message(
        role="tool",
        tool_results=[ToolResult("c1", "failed", is_error=True)],
    )

    value = json.loads(encode_message(message, timestamp=12))
    decoded = decode_record(encode_message(message, timestamp=12))

    assert value["tool_results"][0]["is_error"] is True
    assert decoded == message


def test_boundary_round_trip_preserves_keep_pairing() -> None:
    keep = [
        Message(role="assistant", tool_calls=[ToolCall("c1", "read_file", "{}")]),
        Message(role="tool", tool_results=[ToolResult("c1", "done")]),
    ]
    boundary = CompactBoundary("earlier summary", keep, 13)

    assert decode_record(encode_boundary(boundary)) == boundary


def test_boundary_encodes_summary_and_keep_without_ts() -> None:
    keep = [Message(role="assistant", content="kept")]
    boundary = CompactBoundary("summary", keep, 13)

    value = json.loads(encode_boundary(boundary))

    assert value["type"] == "compact_boundary"
    assert value["content"]["summary"] == "summary"
    assert value["content"]["keep"] == [{"role": "assistant", "content": "kept"}]
    assert value["ts"] == 13


def test_thinking_is_not_persisted() -> None:
    message = Message(
        role="assistant",
        content="answer",
        thinking="private",
        thinking_signature="signature",
    )

    assert decode_record(encode_message(message, timestamp=14)) == Message(
        role="assistant", content="answer"
    )


def test_decode_rejects_malformed_json() -> None:
    assert decode_record("{not json") is None


def test_decode_rejects_unknown_roles_and_types() -> None:
    assert decode_record('{"role":"system","content":"x","ts":1}') is None
    assert decode_record('{"type":"snapshot","ts":1}') is None
    assert decode_record('{"type":"compact","ts":1}') is None


def test_decode_rejects_invalid_boundary_payloads() -> None:
    assert decode_record('{"type":"compact_boundary","ts":1}') is None
    assert (
        decode_record(
            '{"type":"compact_boundary","content":{"summary":1,"keep":[]},"ts":1}'
        )
        is None
    )
    assert (
        decode_record(
            '{"type":"compact_boundary",'
            '"content":{"summary":"s","keep":[{"role":"robot"}]},"ts":1}'
        )
        is None
    )


def test_decode_rejects_non_object_arguments() -> None:
    encoded = (
        '{"role":"assistant","tool_calls":['
        '{"id":"c1","name":"read_file","arguments":"not-object"}],"ts":1}'
    )

    assert decode_record(encoded) is None


def test_decode_accepts_bytes_input() -> None:
    encoded = encode_message(Message(role="user", content="hello"), timestamp=5)

    assert decode_record(encoded) == Message(role="user", content="hello")


@pytest.mark.parametrize(
    "line",
    [
        "",
        "null",
        "42",
        '"text"',
        '{"role":"user","ts":"not-int"}',
    ],
)
def test_decode_is_strict_and_non_throwing(line: str) -> None:
    assert decode_record(line) is None
