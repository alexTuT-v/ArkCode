"""格式 v2 流式投影与配对修复测试。"""

from __future__ import annotations

import copy
from pathlib import Path

from Arkcode.llm import Message, ToolCall, ToolResult
from Arkcode.sessions.load import RESUME_SUMMARY_PREFIX, load_session
from Arkcode.sessions.record import (
    CompactBoundary,
    encode_boundary,
    encode_message,
)


def write_records(session_dir: Path, *records: object) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "conversation.jsonl"
    payload = b"".join(
        encode_message(record, timestamp=1)
        if isinstance(record, Message)
        else encode_boundary(record)
        for record in records
    )
    path.write_bytes(payload)


def test_load_plain_messages_only(tmp_path: Path) -> None:
    write_records(
        tmp_path,
        Message(role="user", content="你好"),
        Message(role="assistant", content="你好，有什么可以帮你？"),
    )

    assert load_session(str(tmp_path)) == [
        Message(role="user", content="你好"),
        Message(role="assistant", content="你好，有什么可以帮你？"),
    ]


def test_last_valid_boundary_replaces_earlier_projection(tmp_path: Path) -> None:
    write_records(
        tmp_path,
        Message(role="user", content="old"),
        CompactBoundary(
            "summary",
            [Message(role="assistant", content="kept")],
            30,
        ),
        Message(role="user", content="new"),
    )

    assert load_session(str(tmp_path)) == [
        Message(role="user", content=RESUME_SUMMARY_PREFIX + "summary"),
        Message(role="assistant", content="kept"),
        Message(role="user", content="new"),
    ]


def test_corrupt_boundary_does_not_clear_valid_history(tmp_path: Path) -> None:
    path = tmp_path / "conversation.jsonl"
    path.write_bytes(
        encode_message(Message(role="user", content="safe"), timestamp=1)
        + b'{"type":"compact_boundary","content":'
    )

    assert load_session(str(tmp_path)) == [Message(role="user", content="safe")]


def test_multiple_boundaries_use_last_one(tmp_path: Path) -> None:
    write_records(
        tmp_path,
        Message(role="user", content="first"),
        CompactBoundary("one", [Message(role="assistant", content="mid")], 10),
        CompactBoundary("two", [Message(role="user", content="late")], 20),
    )

    assert load_session(str(tmp_path)) == [
        Message(role="user", content=RESUME_SUMMARY_PREFIX + "two"),
        Message(role="user", content="late"),
    ]


def test_corrupt_ordinary_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "conversation.jsonl"
    path.write_bytes(
        encode_message(Message(role="user", content="good"), timestamp=1)
        + b"{bad json\n"
        + encode_message(Message(role="assistant", content="fine"), timestamp=2)
    )

    assert load_session(str(tmp_path)) == [
        Message(role="user", content="good"),
        Message(role="assistant", content="fine"),
    ]


def test_truncated_tail_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "conversation.jsonl"
    path.write_bytes(
        encode_message(Message(role="user", content="complete"), timestamp=1)
        + encode_message(Message(role="assistant", content="half"), timestamp=2)[:-4]
    )

    assert load_session(str(tmp_path)) == [Message(role="user", content="complete")]


def test_incomplete_tool_call_gets_interrupted_error_result(tmp_path: Path) -> None:
    write_records(
        tmp_path,
        Message(role="user", content="run"),
        Message(
            role="assistant",
            tool_calls=[ToolCall("c1", "read_file", "{}")],
        ),
    )

    loaded = load_session(str(tmp_path))

    assert loaded[-1].role == "tool"
    assert loaded[-1].tool_results == [
        ToolResult("c1", "工具调用被中断", is_error=True)
    ]


def test_orphan_result_is_omitted(tmp_path: Path) -> None:
    write_records(
        tmp_path,
        Message(role="tool", tool_results=[ToolResult("ghost", "stale")]),
    )

    assert load_session(str(tmp_path)) == []


def test_boundary_keep_pairing_is_preserved(tmp_path: Path) -> None:
    keep = [
        Message(
            role="assistant",
            tool_calls=[ToolCall("c1", "read_file", '{"path":"a"}')],
        ),
        Message(role="tool", tool_results=[ToolResult("c1", "content")]),
    ]
    write_records(
        tmp_path,
        CompactBoundary("summary", copy.deepcopy(keep), 10),
        Message(role="user", content="继续"),
    )

    loaded = load_session(str(tmp_path))

    assert loaded[1:] == [*keep, Message(role="user", content="继续")]
