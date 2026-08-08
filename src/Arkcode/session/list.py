"""扫描并生成可恢复会话列表。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..compact.state import parse_session_time


@dataclass(frozen=True)
class SessionInfo:
    id: str
    title: str
    modified_at: datetime
    model: str
    size: int
    dir: str


def _truncate_title(value: str) -> str:
    return value if len(value) <= 50 else value[:49] + "…"


def list_sessions(sessions_dir: str) -> list[SessionInfo]:
    """返回所有新版有效会话，按文件修改时间倒序。"""

    root = Path(sessions_dir)
    if not root.is_dir():
        return []
    sessions: list[SessionInfo] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        try:
            parse_session_time(directory.name)
        except ValueError:
            continue
        path = directory / "conversation.jsonl"
        if not path.is_file():
            continue
        title = ""
        model = ""
        try:
            with path.open(encoding="utf-8") as source:
                for line in source:
                    try:
                        value = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if not isinstance(value, dict):
                        continue
                    if not model and isinstance(value.get("model"), str):
                        model = value["model"]
                    if value.get("role") == "user":
                        title = _truncate_title(str(value.get("content", "")))
                        break
            stat = path.stat()
        except (OSError, UnicodeDecodeError):
            continue
        sessions.append(
            SessionInfo(
                id=directory.name,
                title=title or "(无标题)",
                modified_at=datetime.fromtimestamp(stat.st_mtime),
                model=model,
                size=stat.st_size,
                dir=str(directory.resolve()),
            )
        )
    return sorted(sessions, key=lambda item: item.modified_at, reverse=True)
