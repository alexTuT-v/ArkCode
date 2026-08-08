"""协议无关的 ReAct Agent 循环编排。"""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    ManageInput,
    RecoveryState,
    TriggerKind,
    manage_context,
    new_session_context,
)
from ..compact.const import AUTO_SAFETY_MARGIN, MANUAL_SAFETY_MARGIN, SUMMARY_RESERVE
from ..compact.token import estimate_tokens, usage_anchor
from ..conversation import Conversation
from ..llm import (
    Message,
    PromptTooLongError,
    Provider,
    Request,
    StreamEnd,
    StreamError,
    System,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCall,
    ToolCallComplete,
    ToolResult,
)
from ..memory import Manager
from ..permission import Decision, Engine, Mode, Outcome, new_engine
from ..prompt import build_system_prompt, gather_environment, plan_reminder
from ..tool import DEFAULT_TIMEOUT, Registry
from ..tool.base import ToolDefinition
from .event import CompactEvent, CompactPhase
from .runtime import SessionRuntime

MAX_ITERATIONS = 25
MAX_UNKNOWN_RUN = 3
PLAN_REMINDER_INTERVAL = 4

NOTICE_MAX_ITER = "（已达最大迭代轮数 25，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED = "（已取消。）"
NOTICE_EMPTY_FINAL = "（模型未返回文本。）"


class Phase(Enum):
    """工具调用在界面上的生命周期阶段。"""

    START = "start"
    END = "end"


@dataclass(frozen=True)
class Usage:
    """一次模型请求的输入与输出 token 用量。"""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    cache_write: int = 0


@dataclass(frozen=True)
class ApprovalRequest:
    """等待界面回传单次权限选择。"""

    name: str
    args: str
    reason: str
    respond: asyncio.Future[Outcome]


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
    approval: ApprovalRequest | None = None
    compact: CompactEvent | None = None


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
    error: Exception | None = None

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

    def __init__(
        self,
        provider: Provider,
        registry: Registry,
        version: str = "dev",
        engine: Engine | None = None,
        *,
        runtime: SessionRuntime | None = None,
        memory_manager: Manager | None = None,
        instruction_text: str = "",
        memory_text: str = "",
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._version = version
        self._engine = engine or new_engine(os.getcwd())[0]
        self._permissions_enabled = engine is not None
        self.runtime = runtime or SessionRuntime(
            replacement=ContentReplacementState(),
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context(os.getcwd()),
        )
        self._memory_manager = memory_manager
        self._instruction_text = instruction_text
        self._memory_text = memory_text
        self._run_lock = asyncio.Lock()

    @staticmethod
    def _recent_turn(messages: list[Message]) -> list[Message]:
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].role == "user":
                return messages[index:]
        return messages

    @staticmethod
    def _has_memory_signal(messages: list[Message]) -> bool:
        keywords = ("记住", "记忆", "别忘", "remember", "memo")
        return any(
            message.role == "user"
            and any(keyword in message.content.lower() for keyword in keywords)
            for message in messages
        )

    def _schedule_memory_update(self, conv: Conversation) -> None:
        self.runtime.turn_count += 1
        manager = self._memory_manager
        if manager is None:
            return
        recent = self._recent_turn(conv.messages())
        if self.runtime.turn_count % 5 == 0 or self._has_memory_signal(recent):
            asyncio.create_task(manager.update_async(recent))

    def _check_permission(
        self,
        mode: Mode,
        call: ToolCall,
        read_only: bool,
    ) -> tuple[Decision, str]:
        if not self._permissions_enabled:
            if mode is Mode.PLAN and not read_only:
                return Decision.DENY, "Plan Mode 不允许执行有副作用的工具"
            return Decision.ALLOW, ""
        return self._engine.check(mode, call, read_only)

    async def _stream_once(
        self,
        conv: Conversation,
        definitions: list[ToolDefinition],
        system: System,
        reminder: str,
        cancel: asyncio.Event,
        state: _StreamState,
    ) -> AsyncIterator[AgentEvent]:
        stream = self._provider.stream(
            Request(
                messages=conv.messages(),
                tools=definitions,
                system=system,
                reminder=reminder,
            )
        )
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

    async def _run_batch(
        self,
        calls: list[ToolCall],
        indexes: range,
        state: _BatchState,
        cancel: asyncio.Event,
        mode: Mode,
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

        async def execute_one(index: int) -> None:
            call = calls[index]
            result = await self._registry.execute(
                call.name,
                call.input,
                timeout=DEFAULT_TIMEOUT,
            )
            if call.name == "read_file" and not result.is_error:
                try:
                    arguments = json.loads(call.input or "{}")
                    path_value = arguments.get("path")
                    if isinstance(path_value, str) and path_value:
                        absolute = Path(path_value).resolve()
                        raw = await asyncio.to_thread(absolute.read_bytes)
                        self.runtime.recovery.record_file(
                            str(absolute),
                            raw.decode("utf-8", errors="replace"),
                        )
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    pass
            state.results[index] = ToolResult(
                tool_call_id=call.id,
                content=result.content,
                is_error=result.is_error,
            )

        index_values = list(indexes)
        read_only_batch = all(
            self._registry.is_read_only(calls[index].name) for index in index_values
        )
        runnable: list[int] = []
        if read_only_batch:
            for index in index_values:
                call = calls[index]
                decision, reason = self._check_permission(mode, call, True)
                if decision is Decision.DENY:
                    state.results[index] = ToolResult(call.id, reason, True)
                else:
                    runnable.append(index)
        else:
            index = index_values[0]
            call = calls[index]
            decision, reason = self._check_permission(mode, call, False)
            if decision is Decision.ASK:
                respond: asyncio.Future[Outcome] = (
                    asyncio.get_running_loop().create_future()
                )
                yield AgentEvent(
                    approval=ApprovalRequest(
                        call.name,
                        _args_preview(call),
                        reason,
                        respond,
                    )
                )
                cancelled = asyncio.create_task(cancel.wait())
                try:
                    approval_waiters: set[asyncio.Future[Any]] = {
                        respond,
                        cancelled,
                    }
                    approval_done, _ = await asyncio.wait(
                        approval_waiters,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if cancelled in approval_done and cancel.is_set():
                        state.completed = False
                        state.results[index] = _cancelled_result(call)
                        if not respond.done():
                            respond.cancel()
                        return
                    outcome = respond.result()
                finally:
                    cancelled.cancel()
                    await asyncio.gather(cancelled, return_exceptions=True)
                    if not respond.done():
                        respond.cancel()

                if outcome is Outcome.DENY_ONCE:
                    decision = Decision.DENY
                    reason = "用户拒绝本次工具调用"
                else:
                    if outcome is Outcome.ALLOW_FOREVER:
                        try:
                            self._engine.persist_local_allow(call)
                        except Exception:
                            # 持久化失败不能改变用户已作出的本次放行决定。
                            pass
                    decision = Decision.ALLOW
            if decision is Decision.DENY:
                state.results[index] = ToolResult(
                    tool_call_id=call.id,
                    content=reason,
                    is_error=True,
                )
            else:
                runnable.append(index)

        tasks = [asyncio.create_task(execute_one(index)) for index in runnable]
        gathered = asyncio.gather(*tasks, return_exceptions=True)
        cancelled = asyncio.create_task(cancel.wait())
        try:
            pending: set[asyncio.Future[Any]] = {gathered, cancelled}
            batch_done, _ = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in batch_done and cancel.is_set():
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
        mode: Mode,
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
                mode,
            ):
                yield event
            if not state.completed:
                for remaining in range(end, len(calls)):
                    state.results[remaining] = _cancelled_result(calls[remaining])
                return
            index = end

    def _manage_input(
        self,
        conv: Conversation,
        definitions: list[ToolDefinition],
        trigger: TriggerKind,
    ) -> ManageInput:
        messages = conv.messages()
        estimated = estimate_tokens(
            self.runtime.usage_anchor,
            messages,
            self.runtime.anchor_msg_len,
        )
        return ManageInput(
            conv=conv,
            provider=self._provider,
            model=self._provider.model,
            context_window=self.runtime.context_window,
            tool_defs=definitions,
            replacement=self.runtime.replacement,
            recovery=self.runtime.recovery,
            auto_tracking=self.runtime.auto_tracking,
            session=self.runtime.session,
            usage_anchor=self.runtime.usage_anchor,
            anchor_msg_len=self.runtime.anchor_msg_len,
            estimated_token=estimated,
            trigger=trigger,
        )

    async def run(
        self,
        conv: Conversation,
        mode: Mode,
        cancel: asyncio.Event,
    ) -> AsyncIterator[AgentEvent]:
        """运行一轮完整 ReAct 循环并以事件流持续报告进度。"""

        async with self._run_lock:
            async for event in self._run_unlocked(conv, mode, cancel):
                yield event

    async def run_force_compact(
        self,
        conv: Conversation,
        tool_defs: list[ToolDefinition],
    ) -> tuple[int, int]:
        """与普通 run 串行地无条件执行一次手动摘要。"""

        async with self._run_lock:
            input_ = self._manage_input(conv, tool_defs, TriggerKind.MANUAL)
            output = await manage_context(input_)
            self.runtime.usage_anchor = 0
            self.runtime.anchor_msg_len = 0
            return output.before_tokens, output.after_tokens

    async def _run_unlocked(
        self,
        conv: Conversation,
        mode: Mode,
        cancel: asyncio.Event,
    ) -> AsyncIterator[AgentEvent]:
        """在调用方持有 run 锁时执行完整 ReAct 循环。"""

        environment = await asyncio.to_thread(
            gather_environment,
            self._version,
            self._provider.model,
        )
        memory_text = (
            self._memory_manager.load_index()
            if self._memory_manager is not None
            else self._memory_text
        )
        system = System(
            stable=build_system_prompt(self._instruction_text, memory_text),
            environment=environment.render(),
        )

        unknown_run = 0
        for iteration in range(1, MAX_ITERATIONS + 1):
            yield AgentEvent(iter=iteration)
            if cancel.is_set():
                _ensure_assistant_tail(conv, NOTICE_CANCELLED)
                return

            definitions = (
                self._registry.read_only_definitions()
                if mode is Mode.PLAN
                else self._registry.definitions()
            )
            manage_input = self._manage_input(conv, definitions, TriggerKind.AUTO)
            auto_threshold = (
                self.runtime.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
            )
            will_auto_compact = (
                self.runtime.context_window > SUMMARY_RESERVE + AUTO_SAFETY_MARGIN
                and manage_input.estimated_token >= auto_threshold
                and not self.runtime.auto_tracking.tripped()
            )
            if will_auto_compact:
                yield AgentEvent(compact=CompactEvent(phase=CompactPhase.BEFORE_AUTO))
            try:
                managed = await manage_context(manage_input)
            except Exception as manage_error:
                if will_auto_compact:
                    yield AgentEvent(
                        compact=CompactEvent(
                            phase=CompactPhase.AFTER_AUTO,
                            before=manage_input.estimated_token,
                            err=manage_error,
                        )
                    )
                yield AgentEvent(err=manage_error)
                _ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                return
            if managed.compacted:
                self.runtime.usage_anchor = 0
                self.runtime.anchor_msg_len = 0
            if will_auto_compact:
                yield AgentEvent(
                    compact=CompactEvent(
                        phase=CompactPhase.AFTER_AUTO,
                        before=managed.before_tokens,
                        after=managed.after_tokens,
                    )
                )

            stream_state = _StreamState()
            reminder = ""
            if mode is Mode.PLAN:
                full = iteration == 1 or (iteration - 1) % PLAN_REMINDER_INTERVAL == 0
                reminder = plan_reminder(full)
            async for event in self._stream_once(
                conv,
                definitions,
                system,
                reminder,
                cancel,
                stream_state,
            ):
                yield event

            if not stream_state.ok:
                if cancel.is_set():
                    _ensure_assistant_tail(conv, NOTICE_CANCELLED)
                    return
                stream_error = stream_state.error or RuntimeError("provider 请求失败")
                if isinstance(stream_error, PromptTooLongError):
                    yield AgentEvent(
                        compact=CompactEvent(phase=CompactPhase.BEFORE_EMERGENCY)
                    )
                    emergency_input = self._manage_input(
                        conv,
                        definitions,
                        TriggerKind.EMERGENCY,
                    )
                    try:
                        emergency = await manage_context(emergency_input)
                    except Exception as compact_error:
                        yield AgentEvent(
                            compact=CompactEvent(
                                phase=CompactPhase.AFTER_EMERGENCY,
                                before=emergency_input.estimated_token,
                                err=compact_error,
                            )
                        )
                        yield AgentEvent(err=compact_error)
                        _ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                        return
                    yield AgentEvent(
                        compact=CompactEvent(
                            phase=CompactPhase.AFTER_EMERGENCY,
                            before=emergency.before_tokens,
                            after=emergency.after_tokens,
                        )
                    )
                    self.runtime.usage_anchor = 0
                    self.runtime.anchor_msg_len = 0
                    if estimate_tokens(0, conv.messages(), 0) >= (
                        self.runtime.context_window - MANUAL_SAFETY_MARGIN
                    ):
                        yield AgentEvent(err=stream_error)
                        _ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                        return
                    stream_state = _StreamState()
                    async for event in self._stream_once(
                        conv,
                        definitions,
                        system,
                        reminder,
                        cancel,
                        stream_state,
                    ):
                        yield event
                    if not stream_state.ok:
                        yield AgentEvent(err=stream_state.error or stream_error)
                        _ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                        return
                else:
                    yield AgentEvent(err=stream_error)
                    _ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                    return

            if stream_state.usage is not None:
                self.runtime.usage_anchor = usage_anchor(stream_state.usage)
                self.runtime.anchor_msg_len = conv.length()
                yield AgentEvent(
                    usage=Usage(
                        input=stream_state.usage.input_tokens,
                        output=stream_state.usage.output_tokens,
                        cache_read=stream_state.usage.cache_read,
                        cache_creation=stream_state.usage.cache_creation,
                        cache_write=stream_state.usage.cache_write,
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
                self._schedule_memory_update(conv)
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
            try:
                async for event in self._execute_batched(
                    calls,
                    cancel,
                    batch_state,
                    mode,
                ):
                    yield event
            except asyncio.CancelledError:
                cancelled_results = [
                    result if result is not None else _cancelled_result(calls[index])
                    for index, result in enumerate(batch_state.results)
                ]
                conv.add_tool_results(cancelled_results)
                _ensure_assistant_tail(conv, NOTICE_CANCELLED)
                raise
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


def new_agent(
    provider: Provider,
    registry: Registry,
    version: str,
    engine: Engine,
) -> Agent:
    """构造启用权限流水线的 Agent。"""

    return Agent(provider, registry, version, engine)
