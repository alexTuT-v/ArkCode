"""统一文件锁与原子 JSON 更新测试。"""

import json
import multiprocessing
import os
import time
from pathlib import Path

import pytest

from Arkcode.teams.storage import FileLock, atomic_update_json


def test_file_lock_acquire_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "x.lock"
    with FileLock(lock_path, acquire_timeout=0.5):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_file_lock_waits_then_times_out(tmp_path: Path) -> None:
    lock_path = tmp_path / "x.lock"
    lock_path.touch()
    with pytest.raises(TimeoutError):
        with FileLock(lock_path, acquire_timeout=0.05):
            pass


def test_file_lock_cleans_stale(tmp_path: Path) -> None:
    lock_path = tmp_path / "x.lock"
    lock_path.touch()
    old = time.time() - 20
    os.utime(lock_path, (old, old))
    with FileLock(lock_path, acquire_timeout=0.5, stale_age=10.0):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_atomic_update_json_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    lock = FileLock(tmp_path / "state.lock")
    updated = atomic_update_json(path, lock, lambda current: [*current, 1])
    assert updated == [1]
    updated = atomic_update_json(path, lock, lambda current: [*current, 2])
    assert json.loads(path.read_text(encoding="utf-8")) == [1, 2]
    assert list(tmp_path.glob(".tmp-*")) == []


def _multiprocess_writer(path: str, lock_path: str, count: int) -> None:
    def mutate(current: object) -> list[int]:
        return [*current, 1] if isinstance(current, list) else [1]

    for _ in range(count):
        atomic_update_json(path, FileLock(lock_path), mutate)


def test_multiprocess_updates_do_not_lose_writes(tmp_path: Path) -> None:
    path = tmp_path / "shared.json"
    lock_path = tmp_path / "shared.lock"
    path.write_text("[]", encoding="utf-8")
    processes = [
        multiprocessing.Process(
            target=_multiprocess_writer,
            args=(str(path), str(lock_path), 10),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
    assert all(process.exitcode == 0 for process in processes)
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value == [1] * 20
