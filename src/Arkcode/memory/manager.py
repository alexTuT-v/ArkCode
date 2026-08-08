"""通过当前模型异步提炼并更新长期记忆。"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any

from ..llm import Message, Provider, Request, StreamError, System, TextDelta
from .prompts import MEMORY_UPDATE_SYSTEM_PROMPT
from .store import Store
from .types import UpdateAction

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
    ) -> None:
        self.project_store = Store(project_dir)
        self.user_store = Store(user_dir)
        self._provider = provider
        self._model = model
        self._lock = asyncio.Lock()

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
        self._provider = provider
        self._model = model

    @staticmethod
    def _action(value: dict[str, Any]) -> UpdateAction:
        return UpdateAction(
            action=str(value.get("action", "")),
            level=str(value.get("level", "")),
            type=str(value.get("type", "")),
            title=str(value.get("title", "")),
            slug=str(value.get("slug", "")),
            content=str(value.get("content", "")),
            filename=str(value.get("filename", "")),
        )

    async def update_async(self, recent_msgs: list[Message]) -> None:
        """串行调用模型提炼最近一轮；任何失败只记录日志。"""

        try:
            async with self._lock:
                if self._provider is None:
                    return
                payload = json.dumps(
                    {
                        "model": self._model,
                        "current_index": self.load_index(),
                        "recent_messages": [asdict(message) for message in recent_msgs],
                    },
                    ensure_ascii=False,
                )
                request = Request(
                    messages=[Message(role="user", content=payload)],
                    tools=None,
                    system=System(stable=MEMORY_UPDATE_SYSTEM_PROMPT),
                )
                chunks: list[str] = []
                async for event in self._provider.stream(request):
                    if isinstance(event, TextDelta):
                        chunks.append(event.text)
                    elif isinstance(event, StreamError):
                        raise event.error
                raw_actions = json.loads("".join(chunks))
                if not isinstance(raw_actions, list):
                    raise ValueError("记忆更新响应必须是 JSON 数组")
                actions = [
                    self._action(value)
                    for value in raw_actions
                    if isinstance(value, dict)
                ]
                self.project_store.apply(
                    [action for action in actions if action.level == "project"]
                )
                self.user_store.apply(
                    [action for action in actions if action.level == "user"]
                )
        except Exception:
            logger.exception("长期记忆更新失败")
