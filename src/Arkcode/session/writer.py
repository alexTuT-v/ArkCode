"""崩溃安全的追加式会话写入器。"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Self

from ..llm import Message

logger = logging.getLogger(__name__)


@dataclass
class Entry:
    """JSONL 中的一条会话记录。"""

    role: str = ""
    content: str = ""
    tool_calls: list[dict[str, object]] | None = None
    tool_results: list[dict[str, object]] | None = None
    ts: int = 0
    model: str | None = None
    type: str | None = None


class Writer:
    """以单行原子追加方式持久化对话消息。"""

    def __init__(self, session_dir: str) -> None:
        directory = Path(session_dir)
        directory.mkdir(parents=True, exist_ok=True)
        self._path = directory / "conversation.jsonl"
        self.path = str(self._path.resolve())
        self._file: BinaryIO = self._path.open("ab")
        self._lock = threading.Lock()
        self._model = ""
        self._has_entries = self._path.stat().st_size > 0

    @classmethod
    def open_existing(cls, session_dir: str) -> Self:
        """打开既有会话；目录缺失时拒绝隐式创建。"""

        if not Path(session_dir).is_dir():
            raise FileNotFoundError(f"会话目录不存在: {session_dir}")
        return cls(session_dir)

    def set_model(self, model: str) -> None:
        """设置首条消息所记录的当前模型。"""

        with self._lock:
            self._model = model

    @staticmethod
    def _entry(message: Message, model: str | None) -> Entry:
        return Entry(
            role=message.role,
            content=message.content,
            tool_calls=[asdict(call) for call in message.tool_calls] or None,
            tool_results=[asdict(result) for result in message.tool_results] or None,
            ts=int(time.time()),
            model=model,
        )

    def _write_unlocked(self, value: dict[str, object]) -> None:
        encoded = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
        self._file.write(encoded)
        self._file.flush()
        os.fsync(self._file.fileno())

    def append(self, msg: Message, model: str, is_first: bool) -> None:
        """追加一条消息，并在首条记录中保存模型名。"""

        with self._lock:
            self._write_unlocked(asdict(self._entry(msg, model if is_first else None)))
            self._has_entries = True

    def write_compact_marker(self) -> None:
        """追加压缩边界标记。"""

        with self._lock:
            self._write_unlocked({"type": "compact", "ts": int(time.time())})
            self._has_entries = True

    def append_all(self, msgs: list[Message]) -> None:
        for message in msgs:
            self.append(message, "", False)

    def on_append(self, message: Message) -> None:
        """供 Conversation 注入的容错追加回调。"""

        try:
            with self._lock:
                first = not self._has_entries
                model = self._model if first else None
                self._write_unlocked(asdict(self._entry(message, model)))
                self._has_entries = True
        except Exception:
            logger.warning("会话消息持久化失败", exc_info=True)

    def on_replace(self, messages: list[Message]) -> None:
        """记录压缩标记和替换后的完整历史。"""

        try:
            with self._lock:
                self._write_unlocked({"type": "compact", "ts": int(time.time())})
                self._has_entries = True
                for message in messages:
                    self._write_unlocked(asdict(self._entry(message, None)))
        except Exception:
            logger.warning("压缩后会话历史持久化失败", exc_info=True)

    def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
