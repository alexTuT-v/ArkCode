"""基于格式 v2 元数据的会话列表与删除。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .meta import SessionMetaStore


@dataclass(frozen=True)
class SessionInfo:
    id: str
    title: str
    modified_at: datetime
    model: str
    size: int
    dir: str


def list_sessions(sessions_dir: str) -> list[SessionInfo]:
    """只读取 format v2 meta.json，按 last_active 倒序。"""

    root = Path(sessions_dir)
    if not root.is_dir():
        return []
    sessions: list[SessionInfo] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        meta = SessionMetaStore(directory).load()
        if meta is None:
            continue
        jsonl = directory / "conversation.jsonl"
        try:
            size = jsonl.stat().st_size
        except OSError:
            continue
        sessions.append(
            SessionInfo(
                id=meta.id,
                title=meta.display_title() or "(无标题)",
                modified_at=meta.last_active,
                model=meta.model,
                size=size,
                dir=str(directory.resolve()),
            )
        )
    return sorted(sessions, key=lambda item: item.modified_at, reverse=True)


def delete_session(sessions_dir: str, session_id: str) -> bool:
    """删除指定会话目录；目录不存在返回 False。"""

    directory = Path(sessions_dir) / session_id
    if not directory.is_dir():
        return False
    shutil.rmtree(directory)
    return True
