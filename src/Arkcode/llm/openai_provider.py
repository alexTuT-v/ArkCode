"""OpenAI Chat Completions API 流式适配器。"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, cast

import openai
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk

from ..config import ProviderConfig
from ..prompt import SYSTEM_PROMPT
from ..tool.contracts import ToolDefinition
from . import (
    ROLE_TOOL,
    Message,
    StreamEnd,
    StreamError,
    StreamEvent,
    TextDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
)


def _effective_system(system_suffix: str) -> str:
    return (
        SYSTEM_PROMPT if not system_suffix else SYSTEM_PROMPT + "\n\n" + system_suffix
    )


def _to_openai_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


def _to_openai_messages(msgs: list[Message]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message in msgs:
        if message.role == ROLE_TOOL:
            messages.extend(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": result.content,
                }
                for result in message.tool_results
            )
            continue
        if message.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": call.input or "{}",
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )
            continue
        messages.append({"role": message.role, "content": message.content})
    return messages


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

    async def stream(
        self,
        msgs: list[Message],
        tools: list[ToolDefinition],
        system_suffix: str = "",
    ) -> AsyncIterator[StreamEvent]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _effective_system(system_suffix)},
            *_to_openai_messages(msgs),
        ]
        try:
            params: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if tools:
                params["tools"] = _to_openai_tools(tools)
            response = await self._client.chat.completions.create(
                **params,
            )
            stream = cast(AsyncStream[ChatCompletionChunk], response)
            tool_calls_buffer: dict[int, dict[str, Any]] = {}
            stop_reason: str = "unknown"
            final_usage: Any | None = None
            async for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    final_usage = usage
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if getattr(choice, "finish_reason", None):
                    stop_reason = str(choice.finish_reason)
                delta = choice.delta
                if delta.content:
                    yield TextDelta(delta.content)
                for call in getattr(delta, "tool_calls", None) or []:
                    item = tool_calls_buffer.setdefault(
                        call.index,
                        {
                            "id": "",
                            "name": "",
                            "args": "",
                            "fragments": [],
                            "started": False,
                        },
                    )
                    if call.id:
                        item["id"] = call.id
                    if call.function.name:
                        item["name"] += call.function.name
                    if not item["started"] and item["id"] and item["name"]:
                        item["started"] = True
                        yield ToolCallStart(item["name"], item["id"])
                        for fragment in item["fragments"]:
                            yield ToolCallDelta(item["id"], fragment)
                        item["fragments"] = []
                    if call.function.arguments:
                        item["args"] += call.function.arguments
                        if item["started"]:
                            yield ToolCallDelta(item["id"], call.function.arguments)
                        else:
                            item["fragments"].append(call.function.arguments)
            for index, item in sorted(tool_calls_buffer.items()):
                if not item["id"] or not item["name"]:
                    yield StreamError(RuntimeError(f"工具调用 {index} 缺少 ID 或名称"))
                    return
                if not item["started"]:
                    yield ToolCallStart(item["name"], item["id"])
                    for fragment in item["fragments"]:
                        yield ToolCallDelta(item["id"], fragment)
                try:
                    arguments = json.loads(item["args"] or "{}")
                except json.JSONDecodeError as exc:
                    yield StreamError(exc)
                    return
                if not isinstance(arguments, dict):
                    yield StreamError(ValueError("工具参数必须是 JSON object"))
                    return
                yield ToolCallComplete(item["id"], item["name"], arguments)
            details = getattr(final_usage, "prompt_tokens_details", None)
            yield StreamEnd(
                stop_reason,
                input_tokens=getattr(final_usage, "prompt_tokens", 0),
                output_tokens=getattr(final_usage, "completion_tokens", 0),
                cache_read=getattr(details, "cached_tokens", 0),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamError(exc)
