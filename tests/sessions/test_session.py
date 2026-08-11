import json
from datetime import timedelta
from pathlib import Path

from Arkcode.llm import Message, ToolCall, ToolResult
from Arkcode.sessions import (
    clean_expired,
    last_message_timestamp,
    load_session,
)
from Arkcode.sessions.journal import SessionJournal
from Arkcode.sessions.meta import SessionMeta, SessionMetaStore


def test_journal_append_and_read_round_trip(tmp_path: Path) -> None:
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

    with SessionJournal(session_dir) as journal:
        for message in messages:
            journal.append_message(message)

    assert load_session(str(session_dir)) == messages


def test_journal_persists_messages_and_last_timestamp(tmp_path: Path) -> None:
    session_dir = tmp_path / "20260808-120000-abcd"
    journal = SessionJournal(session_dir)
    journal.append_message(Message(role="user", content="old"))
    journal.close()

    assert load_session(str(session_dir)) == [Message(role="user", content="old")]
    assert isinstance(last_message_timestamp(str(session_dir)), int)


def test_open_existing_requires_directory_and_appends(tmp_path: Path) -> None:
    missing = tmp_path / "20260808-120000-abcd"
    missing.mkdir()
    journal = SessionJournal(missing)
    journal.append_message(Message(role="user", content="restored"))
    journal.close()

    assert load_session(str(missing))[0].content == "restored"


def test_load_skips_bad_lines_and_truncates_orphaned_tool_call(
    tmp_path: Path,
) -> None:
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


def test_clean_expired_only_removes_old_v2_sessions(tmp_path: Path) -> None:
    from dataclasses import replace
    from datetime import datetime
    from datetime import timedelta as td

    now = datetime.now().astimezone()
    old = tmp_path / f"{(now - td(days=31)).strftime('%Y%m%d-%H%M%S')}-aaaa"
    recent = tmp_path / f"{(now - td(days=1)).strftime('%Y%m%d-%H%M%S')}-bbbb"
    legacy = tmp_path / "1723100000-deadbeef"
    old.mkdir()
    recent.mkdir()
    old_meta = SessionMeta.new(old.name)
    recent_meta = SessionMeta.new(recent.name)
    SessionMetaStore(old).save(replace(old_meta, created_at=now - td(days=31)))
    SessionMetaStore(recent).save(recent_meta)
    legacy.mkdir()

    clean_expired(str(tmp_path), timedelta(days=30))

    assert not old.exists()
    assert recent.exists()
    assert legacy.exists()
