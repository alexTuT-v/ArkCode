"""Anthropic Messages API 流式适配器。"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from ..config import ProviderConfig
from ..prompt import SYSTEM_PROMPT
from . import Message, StreamEvent


class AnthropicProvider:
    """把 Anthropic SDK 事件转换为统一的 ``StreamEvent``。"""

    def __init__(self, cfg: ProviderConfig) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=cfg.api_key,
            base_url=cfg.base_url or None,
        )
        self._name = cfg.name
        self._model = cfg.model
        self._thinking = cfg.thinking

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    async def stream(self, msgs: list[Message]) -> AsyncIterator[StreamEvent]:
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": message.role, "content": message.content} for message in msgs
            ],
        }
        if self._thinking:
            params["thinking"] = {"type": "enabled", "budget_tokens": 2048}

        try:
            async with self._client.messages.stream(**params) as stream:
                async for event in stream:
                    if event.type != "content_block_delta":
                        continue
                    if event.delta.type == "text_delta":
                        yield StreamEvent(text=event.delta.text)
                    # thinking_delta 及其他增量按需求接收即丢弃。
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamEvent(err=exc)
