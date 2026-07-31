"""协议无关的 ReAct Agent 循环编排。"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any

from ..conversation import Conversation
from ..llm import (
    Provider,
    StreamEnd,
    StreamError,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCall,
    ToolCallComplete,
    ToolResult,
)
from ..prompt import PLAN_MODE_REMINDER
from ..tool import DEFAULT_TIMEOUT, Registry
from ..tool.base import ToolDefinition

MAX_ITERATIONS = 25
MAX_UNKNOWN_RUN = 3

NOTICE_MAX_ITER = "（已达最大迭代轮数 25，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED = "（已取消。）"
NOTICE_EMPTY_FINAL = "（模型未返回文本。）"


class Phase(Enum):
    """工具调用在界面上的生命周期阶段。"""

    START = "start"
    END = "end"


class Mode(IntEnum):
    """Agent 当前是普通执行模式还是只读计划模式。"""

    NORMAL = 0
    PLAN = 1


@dataclass(frozen=True)
class Usage:
    """一次模型请求的输入与输出 token 用量。"""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_creation: int = 0


@dataclass(frozen=True)
class ToolEvent:
    """供界面展示的一次工具开始或结束事件。"""

    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass(frozen=True)
class AgentEvent:
    """Agent 对外输出的统一事件。"""

    text: str = ""
    thinking: str = ""
    tool: ToolEvent | None = None
    usage: Usage | None = None
    iter: int = 0
    notice: str = ""
    done: bool = False
    err: Exception | None = None


@dataclass
class _StreamState:
    """一次 provider 流请求累积出的状态。"""

    text: str = ""
    calls: list[ToolCall] | None = None
    usage: StreamEnd | None = None
    thinking: str = ""
    thinking_signature: str = ""
    ended: bool = False
    ok: bool = True

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []


@dataclass
class _BatchState:
    """一次工具批执行累积出的状态。"""

    results: list[ToolResult | None]
    completed: bool = True


class _Cancelled(Exception):
    """内部控制流：本轮已被用户取消。"""


def _args_preview(call: ToolCall) -> str:
    value = call.input or "{}"
    return value if len(value) <= 80 else value[:77] + "..."


def _cancelled_result(call: ToolCall) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        content=NOTICE_CANCELLED,
        is_error=True,
    )


def _ensure_assistant_tail(conv: Conversation, fallback: str) -> None:
    if conv.last_role() != "assistant":
        conv.add_assistant(fallback)


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


class Agent:
    """持续调用模型与工具，直到自然完成或触发停止条件。"""

    def __init__(self, provider: Provider, registry: Registry) -> None:
        self._provider = provider
        self._registry = registry

    async def _stream_once(
        self,
        conv: Conversation,
        definitions: list[ToolDefinition],
        suffix: str,
        cancel: asyncio.Event,
        state: _StreamState,
    ) -> AsyncIterator[AgentEvent]:
        stream = self._provider.stream(conv.messages(), definitions, suffix)
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
                    yield AgentEvent(err=item.error)
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
            yield AgentEvent(err=exc)
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()

    async def _run_batch(
        self,
        calls: list[ToolCall],
        indexes: range,
        state: _BatchState,
        cancel: asyncio.Event,
        allow_side_effects: bool,
    ) -> AsyncIterator[AgentEvent]:
        for index in indexes:
            call = calls[index]
            yield AgentEvent(
                tool=ToolEvent(
                    name=call.name,
                    args=_args_preview(call),
                    phase=Phase.START,
                )
            )

        if cancel.is_set():
            state.completed = False
            for index in indexes:
                state.results[index] = _cancelled_result(calls[index])
            return

        async def run_one(index: int) -> None:
            call = calls[index]
            if not allow_side_effects and not self._registry.is_read_only(call.name):
                state.results[index] = ToolResult(
                    tool_call_id=call.id,
                    content=f"Plan Mode 禁止执行工具: {call.name}",
                    is_error=True,
                )
                return
            else:
                result = await self._registry.execute(
                    call.name,
                    call.input,
                    timeout=DEFAULT_TIMEOUT,
                )
            state.results[index] = ToolResult(
                tool_call_id=call.id,
                content=result.content,
                is_error=result.is_error,
            )

        tasks = [asyncio.create_task(run_one(index)) for index in indexes]
        gathered = asyncio.gather(*tasks, return_exceptions=True)
        cancelled = asyncio.create_task(cancel.wait())
        try:
            pending: set[asyncio.Future[Any]] = {gathered, cancelled}
            done, _ = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in done and cancel.is_set():
                state.completed = False
                for task in tasks:
                    if not task.done():
                        task.cancel()
            await gathered
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            cancelled.cancel()
            await asyncio.gather(
                *tasks,
                cancelled,
                return_exceptions=True,
            )

        for index in indexes:
            call = calls[index]
            result = state.results[index]
            if result is None:
                result = _cancelled_result(call)
                state.results[index] = result
            yield AgentEvent(
                tool=ToolEvent(
                    name=call.name,
                    args=_args_preview(call),
                    phase=Phase.END,
                    result=result.content,
                    is_error=result.is_error,
                )
            )

    async def _execute_batched(
        self,
        calls: list[ToolCall],
        cancel: asyncio.Event,
        state: _BatchState,
        allow_side_effects: bool,
    ) -> AsyncIterator[AgentEvent]:
        index = 0
        while index < len(calls):
            if cancel.is_set():
                state.completed = False
                for remaining in range(index, len(calls)):
                    state.results[remaining] = _cancelled_result(calls[remaining])
                return

            if self._registry.is_read_only(calls[index].name):
                end = index + 1
                while end < len(calls) and self._registry.is_read_only(calls[end].name):
                    end += 1
            else:
                end = index + 1

            async for event in self._run_batch(
                calls,
                range(index, end),
                state,
                cancel,
                allow_side_effects,
            ):
                yield event
            if not state.completed:
                for remaining in range(end, len(calls)):
                    state.results[remaining] = _cancelled_result(calls[remaining])
                return
            index = end

    async def run(
        self,
        conv: Conversation,
        mode: Mode,
        cancel: asyncio.Event,
    ) -> AsyncIterator[AgentEvent]:
        """运行一轮完整 ReAct 循环并以事件流持续报告进度。"""

        if mode is Mode.PLAN:
            definitions = self._registry.read_only_definitions()
            suffix = PLAN_MODE_REMINDER
        else:
            definitions = self._registry.definitions()
            suffix = ""

        unknown_run = 0
        for iteration in range(1, MAX_ITERATIONS + 1):
            yield AgentEvent(iter=iteration)
            if cancel.is_set():
                _ensure_assistant_tail(conv, NOTICE_CANCELLED)
                return

            stream_state = _StreamState()
            async for event in self._stream_once(
                conv,
                definitions,
                suffix,
                cancel,
                stream_state,
            ):
                yield event

            if not stream_state.ok:
                if cancel.is_set():
                    _ensure_assistant_tail(conv, NOTICE_CANCELLED)
                else:
                    _ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                return

            if stream_state.usage is not None:
                yield AgentEvent(
                    usage=Usage(
                        input=stream_state.usage.input_tokens,
                        output=stream_state.usage.output_tokens,
                        cache_read=stream_state.usage.cache_read,
                        cache_creation=stream_state.usage.cache_creation,
                    )
                )

            calls = stream_state.calls or []
            if not calls:
                final = stream_state.text or NOTICE_EMPTY_FINAL
                if not stream_state.text:
                    yield AgentEvent(text=final)
                conv.add_assistant(
                    final,
                    thinking=stream_state.thinking,
                    thinking_signature=stream_state.thinking_signature,
                )
                yield AgentEvent(done=True)
                return

            conv.add_assistant_with_tool_calls(
                stream_state.text,
                calls,
                thinking=stream_state.thinking,
                thinking_signature=stream_state.thinking_signature,
            )
            if all(self._registry.get(call.name) is None for call in calls):
                unknown_run += 1
            else:
                unknown_run = 0

            batch_state = _BatchState(results=[None] * len(calls))
            async for event in self._execute_batched(
                calls,
                cancel,
                batch_state,
                mode is Mode.NORMAL,
            ):
                yield event
            results = [
                result if result is not None else _cancelled_result(calls[index])
                for index, result in enumerate(batch_state.results)
            ]
            conv.add_tool_results(results)

            if not batch_state.completed:
                _ensure_assistant_tail(conv, NOTICE_CANCELLED)
                return

            if unknown_run >= MAX_UNKNOWN_RUN:
                yield AgentEvent(notice=NOTICE_UNKNOWN_TOOLS)
                _ensure_assistant_tail(conv, NOTICE_UNKNOWN_TOOLS)
                yield AgentEvent(done=True)
                return

        yield AgentEvent(notice=NOTICE_MAX_ITER)
        _ensure_assistant_tail(conv, NOTICE_MAX_ITER)
        yield AgentEvent(done=True)
