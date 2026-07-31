"""Anthropic Messages API 流式适配器。"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from ..config import ProviderConfig
from ..prompt import SYSTEM_PROMPT
from . import (
    ROLE_TOOL,
    Message,
    StreamEnd,
    StreamError,
    StreamEvent,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
)
from ..tool.base import ToolDefinition

def _effective_system(system_suffix: str) -> str:
    return (
        SYSTEM_PROMPT if not system_suffix else SYSTEM_PROMPT + "\n\n" + system_suffix
    )


def _to_anthropic_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in tools
    ]


def _to_anthropic_messages(msgs: list[Message]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message in msgs:
        if message.role == ROLE_TOOL:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.tool_call_id,
                            "content": result.content,
                            "is_error": result.is_error,
                        }
                        for result in message.tool_results
                    ],
                }
            )
            continue
        if message.tool_calls or message.thinking:
            content: list[dict[str, Any]] = []
            if message.thinking:
                content.append(
                    {
                        "type": "thinking",
                        "thinking": message.thinking,
                        "signature": message.thinking_signature,
                    }
                )
            if message.content:
                content.append({"type": "text", "text": message.content})
            content.extend(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": json.loads(call.input or "{}"),
                }
                for call in message.tool_calls
            )
            messages.append({"role": "assistant", "content": content})
            continue
        messages.append({"role": message.role, "content": message.content})
    return messages


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

    async def stream(
        self,
        msgs: list[Message],
        tools: list[ToolDefinition],
        system_suffix: str = "",
    ) -> AsyncIterator[StreamEvent]:
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "system": _effective_system(system_suffix),
            "messages": _to_anthropic_messages(msgs),
        }
        if tools:
            params["tools"] = _to_anthropic_tools(tools)
        if self._thinking:
            params["thinking"] = {"type": "enabled", "budget_tokens": 2048}

        try:
            async with self._client.messages.stream(**params) as stream:
                blocks: dict[int, dict[str, str]] = {}
                async for event in stream:
                    if event.type == "content_block_start":
                        index = event.index
                        block = event.content_block
                        if block.type == "thinking":
                            blocks[index] = {
                                "type": "thinking",
                                "text": "",
                                "signature": "",
                            }
                        elif block.type == "tool_use":
                            blocks[index] = {
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "args": "",
                            }
                            yield ToolCallStart(block.name, block.id)
                        continue
                    if event.type == "content_block_delta":
                        index = getattr(event, "index", 0)
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield TextDelta(delta.text)
                        elif delta.type == "thinking_delta":
                            state = blocks.setdefault(
                                index,
                                {"type": "thinking", "text": "", "signature": ""},
                            )
                            state["text"] += delta.thinking
                            yield ThinkingDelta(delta.thinking)
                        elif delta.type == "signature_delta":
                            state = blocks.setdefault(
                                index,
                                {"type": "thinking", "text": "", "signature": ""},
                            )
                            state["signature"] += delta.signature
                        elif delta.type == "input_json_delta":
                            tool_state = blocks.get(index)
                            if (
                                tool_state is None
                                or tool_state.get("type") != "tool_use"
                            ):
                                yield StreamError(RuntimeError("工具参数缺少开始事件"))
                                return
                            tool_state["args"] += delta.partial_json
                            yield ToolCallDelta(tool_state["id"], delta.partial_json)
                        continue
                    if event.type != "content_block_stop":
                        continue
                    completed_state = blocks.pop(event.index, None)
                    if completed_state is None:
                        continue
                    if completed_state["type"] == "thinking":
                        yield ThinkingComplete(
                            completed_state["text"],
                            completed_state["signature"],
                        )
                        continue
                    try:
                        arguments = json.loads(completed_state["args"] or "{}")
                    except json.JSONDecodeError as exc:
                        yield StreamError(exc)
                        return
                    if not isinstance(arguments, dict):
                        yield StreamError(ValueError("工具参数必须是 JSON object"))
                        return
                    yield ToolCallComplete(
                        completed_state["id"],
                        completed_state["name"],
                        arguments,
                    )
                final_message = await stream.get_final_message()
            usage = final_message.usage
            yield StreamEnd(
                final_message.stop_reason or "unknown",
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
                cache_read=getattr(usage, "cache_read_input_tokens", 0),
                cache_creation=getattr(usage, "cache_creation_input_tokens", 0),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamError(exc)
