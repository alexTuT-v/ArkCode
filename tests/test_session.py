import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from Arkcode.conversation import Conversation
from Arkcode.llm import Message, ToolCall, ToolResult
from Arkcode.session import (
    Writer,
    clean_expired,
    last_message_timestamp,
    list_sessions,
    load_session,
)


def test_writer_append_and_read_round_trip(tmp_path: Path) -> None:
    session_dir = tmp_path / "20260808-120000-abcd"
    messages = [
        Message(role="user", content="读取文件"),
        Message(
            role="assistant",
            content="读取中",
            tool_calls=[ToolCall(id="call-1", name="read_file", input="{}")],
        ),
        Message(
            role="tool",
            tool_results=[ToolResult(tool_call_id="call-1", content="done")],
        ),
    ]

    with Writer(str(session_dir)) as writer:
        for index, message in enumerate(messages):
            writer.append(message, "claude-test", index == 0)

    lines = [
        json.loads(line)
        for line in (session_dir / "conversation.jsonl").read_text().splitlines()
    ]
    assert [line["role"] for line in lines] == ["user", "assistant", "tool"]
    assert lines[0]["model"] == "claude-test"
    assert lines[1]["tool_calls"][0]["name"] == "read_file"
    assert lines[2]["tool_results"][0]["content"] == "done"
    assert all(isinstance(line["ts"], int) for line in lines)
    assert load_session(str(session_dir)) == messages


def test_writer_callbacks_persist_first_model_and_replacement(tmp_path: Path) -> None:
    session_dir = tmp_path / "20260808-120000-abcd"
    writer = Writer(str(session_dir))
    writer.set_model("gpt-test")

    writer.on_append(Message(role="user", content="old"))
    writer.on_replace([Message(role="user", content="summary")])
    writer.close()

    lines = [
        json.loads(line)
        for line in (session_dir / "conversation.jsonl").read_text().splitlines()
    ]
    assert lines[0]["model"] == "gpt-test"
    assert lines[1]["type"] == "compact"
    assert load_session(str(session_dir)) == [Message(role="user", content="summary")]
    assert isinstance(last_message_timestamp(str(session_dir)), int)


def test_concurrent_conversation_callbacks_write_complete_json_lines(
    tmp_path: Path,
) -> None:
    writer = Writer(str(tmp_path / "20260808-120000-abcd"))
    conversation = Conversation(on_append=writer.on_append)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: conversation.add_user(f"msg-{index}"), range(40)))
    writer.close()

    lines = (
        (tmp_path / "20260808-120000-abcd" / "conversation.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(lines) == 40
    assert {json.loads(line)["content"] for line in lines} == {
        f"msg-{index}" for index in range(40)
    }


def test_open_existing_requires_directory_and_appends(tmp_path: Path) -> None:
    missing = tmp_path / "20260808-120000-abcd"
    with pytest.raises(FileNotFoundError):
        Writer.open_existing(str(missing))

    missing.mkdir()
    with Writer.open_existing(str(missing)) as writer:
        writer.append(Message(role="user", content="restored"), "", False)
    assert load_session(str(missing))[0].content == "restored"


def test_load_skips_bad_lines_and_truncates_orphaned_tool_call(tmp_path: Path) -> None:
    session_dir = tmp_path / "20260808-120000-abcd"
    session_dir.mkdir()
    path = session_dir / "conversation.jsonl"
    entries = [
        '{"role":"user","content":"ok","ts":1}',
        "{bad json",
        json.dumps(
            {
                "role": "assistant",
                "content": "calling",
                "tool_calls": [{"id": "1", "name": "read", "input": "{}"}],
                "ts": 2,
            }
        ),
    ]
    path.write_text("\n".join(entries), encoding="utf-8")

    assert load_session(str(session_dir)) == [Message(role="user", content="ok")]


def _session(path: Path, title: str, model: str) -> None:
    with Writer(str(path)) as writer:
        writer.append(Message(role="user", content=title), model, True)


def test_list_sessions_sorts_and_skips_old_format(tmp_path: Path) -> None:
    first = tmp_path / "20260806-120000-aaaa"
    second = tmp_path / "20260807-120000-bbbb"
    _session(first, "a" * 60, "old-model")
    _session(second, "new", "new-model")
    _session(tmp_path / "1723100000-deadbeef", "legacy", "legacy-model")
    os.utime(first / "conversation.jsonl", (1, 1))
    os.utime(second / "conversation.jsonl", (2, 2))

    sessions = list_sessions(str(tmp_path))

    assert [item.id for item in sessions] == [second.name, first.name]
    assert sessions[0].model == "new-model"
    assert sessions[1].title == "a" * 49 + "…"
    assert sessions[0].size > 0
    assert sessions[0].dir == str(second.resolve())


def test_clean_expired_only_removes_old_new_format_sessions(tmp_path: Path) -> None:
    now = datetime.now()
    old = tmp_path / f"{(now - timedelta(days=31)).strftime('%Y%m%d-%H%M%S')}-aaaa"
    recent = tmp_path / f"{(now - timedelta(days=1)).strftime('%Y%m%d-%H%M%S')}-bbbb"
    legacy = tmp_path / "1723100000-deadbeef"
    for path in (old, recent, legacy):
        path.mkdir()

    clean_expired(str(tmp_path), timedelta(days=30))

    assert not old.exists()
    assert recent.exists()
    assert legacy.exists()
