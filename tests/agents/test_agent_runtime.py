from pathlib import Path

from Arkcode.agents import SessionRuntime
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
