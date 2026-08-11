"""格式 v2 会话列表与删除测试。"""

from dataclasses import replace
from pathlib import Path

from Arkcode.llm import Message
from Arkcode.sessions import delete_session, list_sessions
from Arkcode.sessions.journal import SessionJournal
from Arkcode.sessions.meta import SessionMeta, SessionMetaStore


def create_v2_session(
    path: Path,
    *,
    title: str = "",
    model: str = "",
    provider: str = "",
) -> SessionMeta:
    journal = SessionJournal(path)
    journal.append_message(Message(role="user", content=title or "hello"))
    journal.close()
    meta = replace(
        SessionMeta.new(path.name),
        title=title or "hello",
        model=model,
        provider=provider,
    )
    SessionMetaStore(path).save(meta)
    return meta


def test_list_only_returns_valid_v2_sessions(tmp_path: Path) -> None:
    valid = tmp_path / "20260810-120000-abcd"
    old = tmp_path / "20260809-120000-efgh"
    corrupt = tmp_path / "20260808-120000-ijkl"
    meta = create_v2_session(valid, title="v2 title", model="claude-test")

    old.mkdir()
    (old / "conversation.jsonl").write_text(
        '{"role":"user","content":"legacy","ts":1}\n', encoding="utf-8"
    )
    corrupt.mkdir()
    (corrupt / "meta.json").write_text("{broken", encoding="utf-8")

    sessions = list_sessions(str(tmp_path))

    assert [item.id for item in sessions] == [valid.name]
    assert sessions[0].title == "v2 title"
    assert sessions[0].model == "claude-test"
    assert sessions[0].modified_at == meta.last_active
    assert sessions[0].size > 0
    assert sessions[0].dir == str(valid.resolve())


def test_list_sorts_by_last_active_descending(tmp_path: Path) -> None:
    older = tmp_path / "20260810-100000-aaaa"
    newer = tmp_path / "20260810-110000-bbbb"
    older_meta = SessionMetaStore(older)
    newer_meta = SessionMetaStore(newer)
    journal = SessionJournal(older)
    journal.append_message(Message(role="user", content="old"))
    journal.close()
    journal = SessionJournal(newer)
    journal.append_message(Message(role="user", content="new"))
    journal.close()
    first = SessionMeta.new(older.name)
    second = SessionMeta.new(newer.name)
    older_meta.save(first)
    newer_meta.save(second)

    sessions = list_sessions(str(tmp_path))

    assert [item.id for item in sessions] == [newer.name, older.name]


def test_list_skips_missing_jsonl(tmp_path: Path) -> None:
    directory = tmp_path / "20260810-120000-abcd"
    directory.mkdir()
    SessionMetaStore(directory).save(SessionMeta.new(directory.name))

    assert list_sessions(str(tmp_path)) == []


def test_delete_session_removes_directory(tmp_path: Path) -> None:
    target = tmp_path / "20260808-120000-abcd"
    target.mkdir(parents=True)
    (target / "conversation.jsonl").write_text("", encoding="utf-8")

    assert delete_session(str(tmp_path), "20260808-120000-abcd") is True
    assert not target.exists()


def test_delete_session_missing_directory_returns_false(tmp_path: Path) -> None:
    assert delete_session(str(tmp_path), "missing-id") is False
