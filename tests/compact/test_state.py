import re
from datetime import datetime
from pathlib import Path

import pytest

from Arkcode.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
    open_session_context,
    parse_session_time,
)


def test_new_session_context_creates_unique_spill_directories(tmp_path: Path) -> None:
    first = new_session_context(str(tmp_path))
    second = new_session_context(str(tmp_path))

    assert first.session_id != second.session_id
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", first.session_id)
    assert Path(first.session_dir).is_dir()
    assert Path(first.spill_dir).is_dir()
    assert Path(first.spill_dir).parts[-2:] == (first.session_id, "tool-results")


def test_open_session_context_reuses_existing_directory_without_creating_it(
    tmp_path: Path,
) -> None:
    created = new_session_context(str(tmp_path))

    opened = open_session_context(str(tmp_path), created.session_id)

    assert opened == created
    with pytest.raises(FileNotFoundError):
        open_session_context(str(tmp_path), "20260808-120000-dead")


def test_parse_session_time_reads_timestamp_prefix() -> None:
    assert parse_session_time("20260808-120102-abcd") == datetime(2026, 8, 8, 12, 1, 2)

    with pytest.raises(ValueError):
        parse_session_time("1723100000-deadbeef")


def test_replacement_decision_is_frozen_and_preview_is_reused() -> None:
    state = ContentReplacementState()
    preview = "preview"
    calls = 0

    def decide() -> tuple[str, str]:
        nonlocal calls
        calls += 1
        return "replaced", preview

    first = state.decide_once("id-1", "original", decide)
    second = state.decide_once("id-1", "different", decide)

    assert first is preview
    assert second is preview
    assert calls == 1


def test_skip_does_not_freeze_decision() -> None:
    state = ContentReplacementState()
    attempts = 0

    def decide() -> tuple[str, str]:
        nonlocal attempts
        attempts += 1
        return ("skip", "") if attempts == 1 else ("kept", "")

    assert state.decide_once("id-1", "original", decide) == "original"
    assert state.decide_once("id-1", "original", decide) == "original"
    assert attempts == 2


def test_circuit_breaker_trips_after_three_failures_and_success_resets() -> None:
    breaker = CompactCircuitBreaker()

    for _ in range(3):
        breaker.record_failure()

    assert breaker.tripped() is True
    breaker.record_success()
    assert breaker.tripped() is False


def test_recovery_state_returns_newest_first_and_snapshot_is_detached(
    tmp_path: Path,
) -> None:
    state = RecoveryState()
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    state.record_file(str(first), "one")
    state.record_file(str(second), "two")

    snapshot = state.snapshot()
    snapshot.clear()

    assert [record.path for record in state.snapshot()] == [str(second), str(first)]
