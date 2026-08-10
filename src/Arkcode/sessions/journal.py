"""崩溃安全的追加式会话日志。"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import BinaryIO, Protocol

from ..llm import Message
from .record import CompactBoundary, encode_boundary, encode_message


class MessageSink(Protocol):
    """普通消息与压缩边界的持久化协议。"""

    def append_message(self, message: Message) -> None: ...

    def append_boundary(self, boundary: CompactBoundary) -> None: ...


class SessionJournal:
    """线程安全的单行 JSONL 追加日志，每条记录 flush + fsync。"""

    def __init__(self, session_dir: str | Path) -> None:
        directory = Path(session_dir)
        directory.mkdir(parents=True, exist_ok=True)
        self._path = directory / "conversation.jsonl"
        self.path = str(self._path.resolve())
        self._lock = threading.Lock()
        self._file: BinaryIO = self._path.open("a+b")
        self._repair_partial_tail()

    def _repair_partial_tail(self) -> None:
        """截掉崩溃残留的半行，保证后续追加不与旧碎片粘连。"""

        self._file.seek(0, os.SEEK_END)
        if self._file.tell() == 0:
            return
        self._file.seek(-1, os.SEEK_END)
        last = self._file.read(1)
        if last == b"\n":
            return
        self._file.seek(0, os.SEEK_SET)
        content = self._file.read()
        last_newline = content.rfind(b"\n")
        truncate_to = last_newline + 1 if last_newline >= 0 else 0
        self._file.seek(truncate_to)
        self._file.truncate()
        self._file.flush()
        os.fsync(self._file.fileno())

    def _append(self, encoded: bytes) -> None:
        with self._lock:
            if self._file.closed:
                raise RuntimeError("Session Journal 已关闭")
            self._file.write(encoded)
            self._file.flush()
            os.fsync(self._file.fileno())

    def append_message(self, message: Message) -> None:
        self._append(encode_message(message))

    def append_boundary(self, boundary: CompactBoundary) -> None:
        self._append(encode_boundary(boundary))

    def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()

    def __enter__(self) -> SessionJournal:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        self.close()
