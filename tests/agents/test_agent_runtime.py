from pathlib import Path

from Arkcode.agents import SessionRuntime
from Arkcode.agents.runtime import ReminderInbox
from Arkcode.context import (
    CompactCircuitBreaker,
    RecoveryState,
    new_session_context,
)


def runtime(path: Path) -> SessionRuntime:
    return SessionRuntime(
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(path)),
    )


def test_reset_for_new_session_replaces_state_and_counters(tmp_path: Path) -> None:
    current = runtime(tmp_path / "current")
    current.usage_anchor = 10
    current.anchor_msg_len = 4
    next_context = new_session_context(str(tmp_path / "next"))

    current.reset_for_new_session(next_context)

    assert current.session == next_context
    assert current.usage_anchor == current.anchor_msg_len == 0


def test_reminder_inbox_is_fifo_and_drain_clears() -> None:
    inbox = ReminderInbox()
    inbox.append("第一条")
    inbox.append("第二条")
    assert inbox.drain() == ["第一条", "第二条"]
    assert inbox.drain() == []


def test_two_runtimes_have_independent_inboxes(tmp_path: Path) -> None:
    first = runtime(tmp_path / "a")
    second = runtime(tmp_path / "b")
    first.inbox.append("只有 first 有")
    assert len(first.inbox) == 1
    assert len(second.inbox) == 0
