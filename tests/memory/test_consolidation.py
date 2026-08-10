"""长期记忆周期整理的门槛、状态和任务所有权测试。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from Arkcode.llm import Message
from Arkcode.memory.consolidation import (
    ConsolidationState,
    Consolidator,
    is_due,
)
from Arkcode.memory.store import Store
from Arkcode.sessions import SessionJournal, SessionMeta, SessionMetaStore


def moment(value: str) -> datetime:
    return datetime.fromisoformat(value)


class ActionSpy:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls = 0
        self.payloads: list[dict[str, object]] = []

    async def execute(
        self,
        system_prompt: str,
        payload: dict[str, object],
    ) -> bool:
        self.calls += 1
        self.payloads.append(payload)
        return self.result


class BlockingActionSpy(ActionSpy):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(
        self,
        system_prompt: str,
        payload: dict[str, object],
    ) -> bool:
        self.calls += 1
        self.payloads.append(payload)
        self.started.set()
        await self.release.wait()
        return True


def create_sessions(root: Path, count: int) -> None:
    for index in range(count):
        directory = root / f"20260810-1200{index:02d}-a{index:03d}"
        journal = SessionJournal(directory)
        journal.append_message(Message(role="user", content=f"session-{index}"))
        journal.close()
        meta = replace(SessionMeta.new(directory.name), title=f"session-{index}")
        SessionMetaStore(directory).save(meta)


def make_consolidator(
    tmp_path: Path,
    actions: ActionSpy,
    *,
    session_count: int = 5,
    now: str = "2026-08-10T10:00:00+08:00",
) -> Consolidator:
    sessions = tmp_path / "sessions"
    create_sessions(sessions, session_count)
    return Consolidator(
        Store(str(tmp_path / "project")),
        Store(str(tmp_path / "user")),
        str(sessions),
        actions,
        now=lambda: moment(now),
    )


def test_due_requires_both_24_hours_and_five_new_sessions() -> None:
    state = ConsolidationState(
        last_success="2026-08-09T10:00:00+08:00",
        session_count=10,
    )

    assert not is_due(state, moment("2026-08-10T09:59:59+08:00"), 15)
    assert not is_due(state, moment("2026-08-10T10:00:00+08:00"), 14)
    assert is_due(state, moment("2026-08-10T10:00:00+08:00"), 15)


def test_missing_or_corrupt_state_uses_epoch(tmp_path: Path) -> None:
    consolidator = make_consolidator(tmp_path, ActionSpy(), session_count=0)

    missing = consolidator.load_state()
    consolidator.state_path.parent.mkdir(parents=True, exist_ok=True)
    consolidator.state_path.write_text("{broken", encoding="utf-8")
    corrupt = consolidator.load_state()

    assert missing.session_count == corrupt.session_count == 0
    assert datetime.fromisoformat(missing.last_success).year == 1970
    assert corrupt == missing


@pytest.mark.asyncio
async def test_schedule_requires_five_sessions(tmp_path: Path) -> None:
    actions = ActionSpy()
    consolidator = make_consolidator(tmp_path, actions, session_count=4)

    consolidator.schedule()
    await asyncio.sleep(0)

    assert actions.calls == 0
    assert consolidator._task is None


@pytest.mark.asyncio
async def test_schedule_runs_only_one_consolidation(tmp_path: Path) -> None:
    actions = BlockingActionSpy()
    consolidator = make_consolidator(tmp_path, actions)

    consolidator.schedule()
    consolidator.schedule()
    await actions.started.wait()

    assert actions.calls == 1
    actions.release.set()
    task = consolidator._task
    assert task is not None
    await task


@pytest.mark.asyncio
async def test_failed_run_does_not_advance_state(tmp_path: Path) -> None:
    consolidator = make_consolidator(tmp_path, ActionSpy(False))
    before = consolidator.load_state()

    consolidator.schedule()
    task = consolidator._task
    assert task is not None
    await task

    assert consolidator.load_state() == before


@pytest.mark.asyncio
async def test_success_advances_time_and_session_baseline(tmp_path: Path) -> None:
    actions = ActionSpy(True)
    consolidator = make_consolidator(tmp_path, actions)

    consolidator.schedule()
    task = consolidator._task
    assert task is not None
    await task

    assert consolidator.load_state() == ConsolidationState(
        last_success="2026-08-10T10:00:00+08:00",
        session_count=5,
    )
    assert actions.payloads[0]["existing_memories"] == []
    assert actions.payloads[0]["memory_documents"] == []
