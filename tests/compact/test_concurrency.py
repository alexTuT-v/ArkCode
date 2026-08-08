from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from Arkcode.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
)


def test_replacement_decision_is_atomic_across_threads() -> None:
    state = ContentReplacementState()
    decision_calls = 0

    def decide() -> tuple[str, str]:
        nonlocal decision_calls
        decision_calls += 1
        return "replaced", "stable-preview"

    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(
            executor.map(
                lambda _: state.decide_once("same-id", "original", decide),
                range(100),
            )
        )

    assert decision_calls == 1
    assert set(results) == {"stable-preview"}


def test_recovery_snapshots_remain_consistent_during_threaded_writes(
    tmp_path: Path,
) -> None:
    state = RecoveryState()

    def write_and_snapshot(index: int) -> None:
        state.record_file(str(tmp_path / f"{index}.txt"), str(index))
        state.snapshot()

    with ThreadPoolExecutor(max_workers=50) as executor:
        list(executor.map(write_and_snapshot, range(100)))

    assert len(state.snapshot()) == 100


def test_circuit_breaker_threaded_updates_do_not_lose_failures() -> None:
    breaker = CompactCircuitBreaker()

    with ThreadPoolExecutor(max_workers=50) as executor:
        list(executor.map(lambda _: breaker.record_failure(), range(100)))

    assert breaker.tripped() is True
