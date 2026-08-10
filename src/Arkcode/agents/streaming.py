"""Provider 流事件到 Agent 事件与流状态的转换。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ..llm import (
    Provider,
    Request,
    StreamEnd,
    StreamError,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCall,
    ToolCallComplete,
)
from .events import AgentEvent


class _Cancelled(Exception):
    """内部控制流：本轮已被用户取消。"""


@dataclass
class StreamState:
    """一次 provider 流请求累积出的状态。"""

    text: str = ""
    calls: list[ToolCall] | None = None
    usage: StreamEnd | None = None
    thinking: str = ""
    thinking_signature: str = ""
    ended: bool = False
    ok: bool = True
    error: Exception | None = None

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []


async def _next_or_cancel(
    stream: AsyncIterator[Any],
    cancel: asyncio.Event,
) -> Any:
    """等待下一段流数据，同时让 per-turn 取消及时打断网络等待。"""

    next_event = asyncio.ensure_future(anext(stream))
    cancelled = asyncio.create_task(cancel.wait())
    try:
        done, _ = await asyncio.wait(
            {next_event, cancelled},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancelled in done and cancel.is_set():
            raise _Cancelled
        return next_event.result()
    finally:
        for task in (next_event, cancelled):
            if not task.done():
                task.cancel()
        await asyncio.gather(
            next_event,
            cancelled,
            return_exceptions=True,
        )


async def stream_once(
    provider: Provider,
    request: Request,
    cancel: asyncio.Event,
    state: StreamState,
) -> AsyncIterator[AgentEvent]:
    """消费一次 provider 流，转换为 AgentEvent 并累积状态。"""

    stream = provider.stream(request)
    try:
        while True:
            if cancel.is_set():
                raise _Cancelled
            try:
                item = await _next_or_cancel(stream, cancel)
            except StopAsyncIteration:
                break
            if isinstance(item, StreamError):
                state.ok = False
                state.error = item.error
                return
            if isinstance(item, TextDelta):
                state.text += item.text
                yield AgentEvent(text=item.text)
                continue
            if isinstance(item, ThinkingDelta):
                state.thinking += item.text
                yield AgentEvent(thinking=item.text)
                continue
            if isinstance(item, ThinkingComplete):
                state.thinking = item.thinking
                state.thinking_signature = item.signature
                continue
            if isinstance(item, ToolCallComplete):
                assert state.calls is not None
                state.calls.append(
                    ToolCall(
                        id=item.tool_id,
                        name=item.tool_name,
                        input=json.dumps(item.arguments, ensure_ascii=False),
                    )
                )
                continue
            if isinstance(item, StreamEnd):
                state.usage = item
                state.ended = True
                break
        if not state.ended:
            state.ok = False
            yield AgentEvent(err=RuntimeError("provider 流未发送结束事件"))
    except _Cancelled:
        state.ok = False
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        state.ok = False
        state.error = exc
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()
