from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from Arkcode.context.state import (
    CompactCircuitBreaker,
    RecoveryState,
)


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
