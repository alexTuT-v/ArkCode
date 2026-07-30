"""OpenAI Chat Completions API 流式适配器。"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import openai
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk

from ..config import ProviderConfig
from ..prompt import SYSTEM_PROMPT
from . import Message, StreamEvent


class OpenAIProvider:
    """把 OpenAI SDK 数据块转换为统一的 ``StreamEvent``。"""

    def __init__(self, cfg: ProviderConfig) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url or None,
        )
        self._name = cfg.name
        self._model = cfg.model

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    async def stream(self, msgs: list[Message]) -> AsyncIterator[StreamEvent]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *[{"role": message.role, "content": message.content} for message in msgs],
        ]
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
                stream=True,
            )
            stream = cast(AsyncStream[ChatCompletionChunk], response)
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield StreamEvent(text=delta)
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamEvent(err=exc)
