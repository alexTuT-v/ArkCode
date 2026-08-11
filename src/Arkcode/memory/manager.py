"""通过当前模型异步提炼并更新长期记忆。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

from ..llm import Provider
from .actions import MemoryActionService
from .consolidation import Consolidator
from .prompts import MEMORY_EXTRACTION_SYSTEM_PROMPT
from .recall import Recall
from .store import Store
from .types import MemoryEntry, MemoryScope, MemoryTurn

logger = logging.getLogger(__name__)
_MAX_INDEX_BYTES = 25 * 1024
_TRUNCATED = "(index truncated)"


class Manager:
    """协调项目级与用户级记忆索引和后台更新。"""

    def __init__(
        self,
        project_dir: str,
        user_dir: str,
        provider: Provider | None,
        model: str,
        sessions_dir: str | None = None,
    ) -> None:
        self.project_store = Store(project_dir)
        self.user_store = Store(user_dir)
        self._actions = MemoryActionService(
            self.project_store,
            self.user_store,
            provider,
            model,
        )
        self._recall = Recall(
            self.project_store,
            self.user_store,
            provider,
            model,
        )
        self._consolidator = (
            Consolidator(
                self.project_store,
                self.user_store,
                sessions_dir,
                self._actions,
            )
            if sessions_dir is not None
            else None
        )
        self._pending_turns: list[MemoryTurn] = []
        self._retry_batch: tuple[list[MemoryTurn], int] | None = None
        self._extract_task: asyncio.Task[None] | None = None

    def load_index(self) -> str:
        parts = [
            value
            for value in (
                self.project_store.load_index(),
                self.user_store.load_index(),
            )
            if value
        ]
        combined = "\n\n".join(parts)
        encoded = combined.encode("utf-8")
        if len(encoded) <= _MAX_INDEX_BYTES:
            return combined
        marker = _TRUNCATED.encode()
        shortened = encoded[: _MAX_INDEX_BYTES - len(marker)]
        while True:
            try:
                return shortened.decode("utf-8") + _TRUNCATED
            except UnicodeDecodeError:
                shortened = shortened[:-1]

    def set_provider(self, provider: Provider, model: str) -> None:
        self._actions.set_provider(provider, model)
        self._recall.set_provider(provider, model)

    def list_files(self) -> tuple[list[str], list[str]]:
        """列出项目级和用户级 Markdown 记忆文件。"""

        def list_store(store: Store) -> list[str]:
            try:
                return sorted(path.name for path in store._dir.glob("*.md"))
            except OSError:
                logger.warning("读取记忆文件列表失败: %s", store._dir, exc_info=True)
                return []

        return list_store(self.project_store), list_store(self.user_store)

    def clear(self) -> None:
        """清空项目级与用户级 store 的全部记忆笔记。"""

        self.project_store.clear()
        self.user_store.clear()

    def dirs(self) -> tuple[str, str]:
        return str(self.project_store._dir), str(self.user_store._dir)

    def list_entries(self) -> list[MemoryEntry]:
        return [
            *self.project_store.list_entries(MemoryScope.PROJECT),
            *self.user_store.list_entries(MemoryScope.USER),
        ]

    async def recall(self, query: str) -> str:
        return await self._recall.select(query)

    def schedule_consolidation(self) -> None:
        if self._consolidator is not None:
            self._consolidator.schedule()

    def has_pending_extraction(self) -> bool:
        return bool(
            self._pending_turns
            or self._retry_batch is not None
            or (self._extract_task is not None and not self._extract_task.done())
        )

    def _ensure_extract_task(self) -> None:
        if self._extract_task is None or self._extract_task.done():
            self._extract_task = asyncio.create_task(self._drain_extraction())

    def schedule_extract(self, turn: MemoryTurn) -> None:
        self._pending_turns.append(turn)
        self._ensure_extract_task()

    async def _drain_extraction(self) -> None:
        while True:
            if self._retry_batch is not None:
                batch, failures = self._retry_batch
                self._retry_batch = None
            elif self._pending_turns:
                batch = self._pending_turns
                self._pending_turns = []
                failures = 0
            else:
                return

            success = await self._actions.execute(
                MEMORY_EXTRACTION_SYSTEM_PROMPT,
                {
                    "existing_memories": [
                        asdict(entry) for entry in self.list_entries()
                    ],
                    "turns": [asdict(turn) for turn in batch],
                },
            )
            if success:
                continue
            if failures == 0:
                self._retry_batch = (batch, 1)
                return
            logger.error("长期记忆提取连续失败两次，丢弃当前批次")

    async def flush_extraction(self, timeout: float = 3.0) -> None:
        async def flush_all() -> None:
            while self.has_pending_extraction():
                self._ensure_extract_task()
                task = self._extract_task
                if task is not None:
                    await task

        try:
            await asyncio.wait_for(flush_all(), timeout=timeout)
        except TimeoutError:
            logger.warning("长期记忆提取退出收尾超时")
            task = self._extract_task
            if task is not None and not task.done():
                task.cancel()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
        finally:
            self._extract_task = None

    async def shutdown(self) -> None:
        await self.flush_extraction(timeout=3.0)
        if self._consolidator is not None:
            await self._consolidator.shutdown()
