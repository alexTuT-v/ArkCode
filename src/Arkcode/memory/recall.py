"""根据当前问题选择并安全读取相关长期记忆。"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict

from ..llm import Message, Provider, Request, System
from ..prompts import system_reminder
from .actions import collect_text
from .prompts import MEMORY_RECALL_SYSTEM_PROMPT
from .store import Store
from .types import MemoryEntry, MemoryScope

logger = logging.getLogger(__name__)
_MAX_SELECTED = 5
_MAX_BYTES = 25 * 1024
_HEADER = "Relevant long-term memories (read-only):"
_TRUNCATED = "(memory truncated)"


def _truncate_utf8(value: str, limit: int) -> str:
    data = value.encode("utf-8")[: max(0, limit)]
    while data:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            data = data[:-1]
    return ""


def _wrap(blocks: list[str]) -> str:
    return system_reminder(f"{_HEADER}\n" + "\n\n".join(blocks))


def _render(selected: list[tuple[MemoryEntry, str]]) -> str:
    blocks: list[str] = []
    for entry, document in selected:
        opening = f'<memory key="{entry.key}">\n'
        closing = "\n</memory>"
        block = f"{opening}{document}{closing}"
        candidate = _wrap([*blocks, block])
        if len(candidate.encode("utf-8")) <= _MAX_BYTES:
            blocks.append(block)
            continue

        truncated_suffix = f"\n{_TRUNCATED}{closing}"
        empty_candidate = _wrap([*blocks, f"{opening}{truncated_suffix}"])
        available = _MAX_BYTES - len(empty_candidate.encode("utf-8"))
        if available > 0:
            blocks.append(
                f"{opening}{_truncate_utf8(document, available)}{truncated_suffix}"
            )
        break
    return _wrap(blocks) if blocks else ""


class Recall:
    """使用模型选择候选 key，并通过 Store 读取对应全文。"""

    def __init__(
        self,
        project_store: Store,
        user_store: Store,
        provider: Provider | None,
        model: str,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._project = project_store
        self._user = user_store
        self._provider = provider
        self._model = model
        self._timeout_seconds = timeout_seconds

    def set_provider(self, provider: Provider, model: str) -> None:
        self._provider = provider
        self._model = model

    def _entries(self) -> list[MemoryEntry]:
        return [
            *self._project.list_entries(MemoryScope.PROJECT),
            *self._user.list_entries(MemoryScope.USER),
        ]

    async def select(self, query: str) -> str:
        entries = self._entries()
        provider = self._provider
        if not query.strip() or not entries or provider is None:
            return ""
        request = Request(
            messages=[
                Message(
                    role="user",
                    content=json.dumps(
                        {
                            "model": self._model,
                            "query": query,
                            "candidates": [asdict(entry) for entry in entries],
                        },
                        ensure_ascii=False,
                    ),
                )
            ],
            tools=None,
            system=System(stable=MEMORY_RECALL_SYSTEM_PROMPT),
        )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                raw = await collect_text(provider, request)
            keys = json.loads(raw)
            if not isinstance(keys, list) or any(
                not isinstance(key, str) for key in keys
            ):
                raise ValueError("记忆召回响应必须是字符串数组")
            by_key = {entry.key: entry for entry in entries}
            unique: list[MemoryEntry] = []
            seen: set[str] = set()
            for key in keys:
                if key in seen or key not in by_key:
                    continue
                seen.add(key)
                unique.append(by_key[key])
                if len(unique) >= _MAX_SELECTED:
                    break
            selected: list[tuple[MemoryEntry, str]] = []
            for entry in unique:
                store = (
                    self._project if entry.scope is MemoryScope.PROJECT else self._user
                )
                selected.append((entry, store.read(entry.filename)))
            return _render(selected)
        except Exception:
            logger.warning("长期记忆召回失败，已降级为精简索引", exc_info=True)
            return ""
