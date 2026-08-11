"""Worktree session 持久化。"""

from __future__ import annotations

import json
from pathlib import Path

from .manifest import atomic_write_json
from .models import WorktreeSession


class WorktreeSessionStore:
    def __init__(self, session_file: str | Path) -> None:
        self._path = Path(session_file)

    def save(self, session: WorktreeSession | None) -> None:
        if session is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("null", encoding="utf-8")
            return
        atomic_write_json(self._path, session.to_dict())

    def load(self) -> WorktreeSession | None:
        if not self._path.is_file():
            return None
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if value is None or value == {}:
            return None
        if not isinstance(value, dict):
            return None
        try:
            return WorktreeSession.from_dict(value)
        except (KeyError, TypeError, ValueError):
            return None
