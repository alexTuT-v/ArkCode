"""O_EXCL 文件锁与原子 JSON 更新（mewCode 风格）。"""

from __future__ import annotations

import json
import os
import random
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class FileLock:
    """基于 O_CREAT|O_EXCL 的同步文件锁。"""

    def __init__(
        self,
        path: str | Path,
        *,
        acquire_timeout: float = 5.0,
        stale_age: float = 10.0,
        initial_backoff: float = 0.005,
        max_backoff: float = 0.08,
    ) -> None:
        self._path = Path(path)
        self._acquire_timeout = acquire_timeout
        self._stale_age = stale_age
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff

    def _is_stale(self) -> bool:
        try:
            return time.time() - self._path.stat().st_mtime > self._stale_age
        except FileNotFoundError:
            return False

    def __enter__(self) -> FileLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._acquire_timeout
        backoff = self._initial_backoff
        while True:
            try:
                fd = os.open(
                    self._path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
                os.close(fd)
                return self
            except FileExistsError:
                if self._is_stale():
                    self._path.unlink(missing_ok=True)
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"获取文件锁超时: {self._path}"
                    ) from None
                time.sleep(backoff + random.uniform(0, backoff * 0.5))
                backoff = min(backoff * 2, self._max_backoff)

    def __exit__(self, *exc: object) -> None:
        self._path.unlink(missing_ok=True)


def atomic_update_json(
    path: str | Path,
    lock: FileLock,
    mutate: Callable[[Any], Any],
) -> Any:
    """在锁临界区内完成完整 read-modify-write，并原子替换。"""

    target = Path(path)
    with lock:
        current: Any
        if target.is_file():
            current = json.loads(target.read_text(encoding="utf-8"))
        else:
            current = []
        updated = mutate(current)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=target.parent,
                prefix=".tmp-",
                suffix=".json",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(updated, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)
        return updated
