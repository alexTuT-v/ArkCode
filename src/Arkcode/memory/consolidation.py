"""长期记忆的周期整理与去重调度。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from ..sessions import list_sessions
from .prompts import MEMORY_CONSOLIDATION_SYSTEM_PROMPT
from .store import Store
from .types import MemoryEntry, MemoryScope

logger = logging.getLogger(__name__)
_STATE_FILE = ".consolidation-state.json"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class ActionExecutor(Protocol):
    async def execute(
        self,
        system_prompt: str,
        payload: dict[str, object],
    ) -> bool: ...


@dataclass(frozen=True)
class ConsolidationState:
    last_success: str
    session_count: int


def is_due(
    state: ConsolidationState,
    now: datetime,
    current_session_count: int,
) -> bool:
    last = datetime.fromisoformat(state.last_success)
    return (
        now - last >= timedelta(hours=24)
        and current_session_count - state.session_count >= 5
    )


class Consolidator:
    """在双门槛满足时启动单个后台整理任务。"""

    def __init__(
        self,
        project_store: Store,
        user_store: Store,
        sessions_dir: str,
        actions: ActionExecutor,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._project = project_store
        self._user = user_store
        self._sessions_dir = sessions_dir
        self._actions = actions
        self._now = now or (lambda: datetime.now().astimezone())
        self.state_path = Path(project_store._dir) / _STATE_FILE
        self._task: asyncio.Task[None] | None = None

    def load_state(self) -> ConsolidationState:
        fallback = ConsolidationState(_EPOCH.isoformat(), 0)
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                return fallback
            last_success = value.get("last_success")
            session_count = value.get("session_count")
            if not isinstance(last_success, str) or not isinstance(session_count, int):
                return fallback
            parsed = datetime.fromisoformat(last_success)
            if parsed.tzinfo is None or session_count < 0:
                return fallback
            return ConsolidationState(last_success, session_count)
        except (OSError, ValueError, json.JSONDecodeError):
            return fallback

    def _save_state(self, state: ConsolidationState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)

    def _entries(self) -> list[MemoryEntry]:
        return [
            *self._project.list_entries(MemoryScope.PROJECT),
            *self._user.list_entries(MemoryScope.USER),
        ][:200]

    def schedule(self) -> None:
        if self._task is not None and not self._task.done():
            return
        current_count = len(list_sessions(self._sessions_dir))
        current_time = self._now()
        if not is_due(self.load_state(), current_time, current_count):
            return
        self._task = asyncio.create_task(self._run(current_time, current_count))

    async def _run(self, current_time: datetime, current_count: int) -> None:
        entries = self._entries()
        documents: list[dict[str, str]] = []
        for entry in entries:
            store = self._project if entry.scope is MemoryScope.PROJECT else self._user
            try:
                content = store.read(entry.filename)
            except OSError:
                logger.warning("读取待整理记忆失败: %s", entry.key, exc_info=True)
                continue
            documents.append({"key": entry.key, "content": content})
        success = await self._actions.execute(
            MEMORY_CONSOLIDATION_SYSTEM_PROMPT,
            {
                "existing_memories": [asdict(entry) for entry in entries],
                "memory_documents": documents,
            },
        )
        if success:
            self._save_state(
                ConsolidationState(current_time.isoformat(), current_count)
            )

    async def shutdown(self) -> None:
        task = self._task
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
