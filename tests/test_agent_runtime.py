from pathlib import Path

from Arkcode.agent import SessionRuntime
from Arkcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)


def runtime(path: Path) -> SessionRuntime:
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(path)),
    )


def test_reset_for_new_session_replaces_state_and_counters(tmp_path: Path) -> None:
    current = runtime(tmp_path / "current")
    previous_replacement = current.replacement
    current.usage_anchor = 10
    current.anchor_msg_len = 4
    current.turn_count = 3
    next_context = new_session_context(str(tmp_path / "next"))

    current.reset_for_new_session(next_context)

    assert current.session == next_context
    assert current.replacement is not previous_replacement
    assert current.usage_anchor == current.anchor_msg_len == current.turn_count == 0
