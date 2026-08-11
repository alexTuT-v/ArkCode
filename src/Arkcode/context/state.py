"""单次进程会话中的上下文管理状态。"""

from __future__ import annotations

import copy
import logging
import random
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .constants import MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionContext:
    """本进程的会话标识与工具结果落盘目录。"""

    session_id: str
    session_dir: str
    spill_dir: str


def _new_session_id() -> str:
    try:
        suffix = secrets.token_hex(2)
    except Exception:
        logger.warning("安全随机会话标识生成失败，已使用时间种子降级")
        suffix = random.Random(time.time()).randbytes(2).hex()
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{suffix}"


def new_session_context(workspace: str) -> SessionContext:
    """创建唯一会话目录并返回其稳定路径。"""

    session_id = _new_session_id()
    session_dir = Path(workspace) / ".Arkcode" / "sessions" / session_id
    spill_dir = session_dir / "tool-results"
    spill_dir.mkdir(parents=True, exist_ok=True)
    return SessionContext(
        session_id=session_id,
        session_dir=str(session_dir),
        spill_dir=str(spill_dir),
    )


def open_session_context(workspace: str, session_id: str) -> SessionContext:
    """打开已有会话目录，不隐式创建缺失目录。"""

    session_dir = Path(workspace) / ".Arkcode" / "sessions" / session_id
    if not session_dir.is_dir():
        raise FileNotFoundError(f"会话目录不存在: {session_dir}")
    return SessionContext(
        session_id=session_id,
        session_dir=str(session_dir),
        spill_dir=str(session_dir / "tool-results"),
    )


def parse_session_time(session_id: str) -> datetime:
    """从新版可读会话 ID 中解析创建时间。"""

    return datetime.strptime(session_id[:15], "%Y%m%d-%H%M%S")


class CompactCircuitBreaker:
    """连续失败三次后暂停自动摘要，成功后立即复位。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._consecutive_failures = 0

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1

    def tripped(self) -> bool:
        with self._lock:
            return self._consecutive_failures >= MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES


@dataclass(frozen=True)
class FileReadRecord:
    """最近一次成功读取文件时保存的纯净内容。"""

    path: str
    content: str
    timestamp: datetime


class RecoveryState:
    """线程安全地追踪每个文件最近一次成功读取的快照。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._files: dict[str, FileReadRecord] = {}

    def record_file(self, path: str, content: str) -> None:
        normalized = str(Path(path).resolve())
        with self._lock:
            self._files[normalized] = FileReadRecord(
                path=normalized,
                content=content,
                timestamp=datetime.now(),
            )

    def snapshot(self) -> list[FileReadRecord]:
        with self._lock:
            records = [copy.copy(record) for record in self._files.values()]
        return sorted(records, key=lambda record: record.timestamp, reverse=True)
