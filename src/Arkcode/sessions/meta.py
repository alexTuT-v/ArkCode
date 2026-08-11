"""格式 v2 会话元数据与原子存储。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SessionMeta:
    """会话级展示与恢复元数据。"""

    format_version: int
    id: str
    title: str
    provider: str
    model: str
    message_count: int
    total_tokens: int
    created_at: datetime
    last_active: datetime

    @classmethod
    def new(cls, session_id: str) -> SessionMeta:
        now = datetime.now().astimezone()
        return cls(
            format_version=2,
            id=session_id,
            title="",
            provider="",
            model="",
            message_count=0,
            total_tokens=0,
            created_at=now,
            last_active=now,
        )

    def display_title(self) -> str:
        return self.title if len(self.title) <= 50 else self.title[:49] + "…"


class SessionMetaStore:
    """通过同目录临时文件 + os.replace 原子更新 meta.json。"""

    def __init__(self, session_dir: str | Path) -> None:
        self._directory = Path(session_dir)
        self._path = self._directory / "meta.json"
        self._lock = threading.RLock()

    def load(self) -> SessionMeta | None:
        with self._lock:
            try:
                value = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                return None
            if not isinstance(value, dict):
                return None
            if value.get("format_version") != 2:
                return None
            try:
                return SessionMeta(
                    format_version=int(value["format_version"]),
                    id=str(value["id"]),
                    title=str(value.get("title", "")),
                    provider=str(value.get("provider", "")),
                    model=str(value.get("model", "")),
                    message_count=int(value.get("message_count", 0)),
                    total_tokens=int(value.get("total_tokens", 0)),
                    created_at=datetime.fromisoformat(value["created_at"]),
                    last_active=datetime.fromisoformat(value["last_active"]),
                )
            except (KeyError, ValueError, TypeError):
                return None

    def save(self, meta: SessionMeta) -> None:
        with self._lock:
            self._directory.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "format_version": meta.format_version,
                "id": meta.id,
                "title": meta.title,
                "provider": meta.provider,
                "model": meta.model,
                "message_count": meta.message_count,
                "total_tokens": meta.total_tokens,
                "created_at": meta.created_at.isoformat(),
                "last_active": meta.last_active.isoformat(),
            }
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=self._directory,
                    prefix=".meta-",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    temp_path = Path(handle.name)
                    json.dump(payload, handle, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self._path)
            finally:
                if temp_path is not None and temp_path.exists():
                    temp_path.unlink(missing_ok=True)

    def update(self, **changes: Any) -> SessionMeta:
        with self._lock:
            current = self.load()
            if current is None:
                current = SessionMeta.new(str(self._directory.name))
            updated = replace(current, **changes)
            self.save(updated)
            return updated
