"""崩溃安全 Journal 测试。"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from Arkcode.llm import Message
from Arkcode.sessions.journal import SessionJournal
from Arkcode.sessions.record import CompactBoundary, encode_message


def test_journal_appends_messages_and_boundary(tmp_path: Path) -> None:
    journal = SessionJournal(tmp_path)
    journal.append_message(Message(role="user", content="hello"))
    journal.append_boundary(CompactBoundary("summary", [], 20))
    journal.close()

    values = [
        json.loads(line)
        for line in (tmp_path / "conversation.jsonl").read_text().splitlines()
    ]
    assert [value.get("type", "message") for value in values] == [
        "message",
        "compact_boundary",
    ]


def test_closed_journal_rejects_append(tmp_path: Path) -> None:
    journal = SessionJournal(tmp_path)
    journal.close()
    journal.close()

    with pytest.raises(RuntimeError, match="已关闭"):
        journal.append_message(Message(role="user", content="late"))


def test_concurrent_appends_produce_independent_lines(tmp_path: Path) -> None:
    journal = SessionJournal(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda index: journal.append_message(
                    Message(role="user", content=f"msg-{index}")
                ),
                range(40),
            )
        )
    journal.close()

    lines = (
        (tmp_path / "conversation.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert len(lines) == 40
    assert {json.loads(line)["content"] for line in lines} == {
        f"msg-{index}" for index in range(40)
    }


def test_every_append_fsyncs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    journal = SessionJournal(tmp_path)
    journal.append_message(Message(role="user", content="one"))
    journal.append_message(Message(role="user", content="two"))
    journal.append_boundary(CompactBoundary("summary", [], 1))
    journal.close()

    assert len(calls) >= 3


def test_open_truncates_partial_tail_before_append(tmp_path: Path) -> None:
    path = tmp_path / "conversation.jsonl"
    path.write_bytes(
        encode_message(Message(role="user", content="safe"), timestamp=1)
        + b'{"type":"compact_boundary","content":'
    )

    journal = SessionJournal(tmp_path)
    journal.append_message(Message(role="user", content="after"))
    journal.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["content"] for line in lines] == ["safe", "after"]
