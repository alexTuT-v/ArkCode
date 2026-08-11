"""协议无关的 ReAct Agent 循环编排。"""

import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator

from ..context import (
    CompactCircuitBreaker,
    ManageInput,
    ManageOutput,
    RecoveryState,
    TriggerKind,
    build_manage_input,
    manage_context,
    new_session_context,
)
from ..context.constants import (
    AUTO_SAFETY_MARGIN,
    MANUAL_SAFETY_MARGIN,
    SUMMARY_RESERVE,
)
from ..context.spill import prepare_tool_results
from ..context.tokens import estimate_tokens, usage_anchor
from ..conversations import Conversation
from ..llm import (
    PromptTooLongError,
    Provider,
    Request,
    System,
)
from ..memory import Manager, MemoryTurn
from ..permissions import Engine, Mode
from ..permissions.scope import PermissionLedger, PermissionScope
from ..prompts import (
    build_system_prompt,
    combine_reminders,
    deferred_tools_reminder,
    gather_environment,
    plan_reminder,
    render_active_skills,
)
from ..sessions.record import CompactBoundary
from ..tools import Registry
from ..tools.base import ToolDefinition
from .events import (
    NOTICE_CANCELLED,
    NOTICE_EMPTY_FINAL,
    NOTICE_MAX_ITER,
    NOTICE_STREAM_ERR,
    NOTICE_UNKNOWN_TOOLS,
    AgentEvent,
    CompactEvent,
    CompactPhase,
    Phase,
    RunResult,
    RunStatus,
    Usage,
)
from .execution import (
    ApprovalBroker,
    BatchState,
    ToolExecutor,
    cancelled_result,
)
from .identity import AgentIdentity
from .runtime import SessionRuntime
from .streaming import StreamState, stream_once

MAX_ITERATIONS = 25
MAX_UNKNOWN_RUN = 3
PLAN_REMINDER_INTERVAL = 4


def _ensure_assistant_tail(conv: Conversation, fallback: str) -> None:
    if conv.last_role() != "assistant":
        conv.add_assistant(fallback)


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
        instructions_content: str = "",
        max_turns: int = MAX_ITERATIONS,
        identity: AgentIdentity | None = None,
        permission_scope: PermissionScope | None = None,
        permission_ledger: PermissionLedger | None = None,
        approval_broker: ApprovalBroker | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._version = version
        self._engine = engine
        self._permissions_enabled = engine is not None
        self.runtime = runtime or SessionRuntime(
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context(os.getcwd()),
        )
        self._memory_manager = memory_manager
        self._instruction_text = instruction_text
        self._memory_text = memory_text
        self._instructions_content = instructions_content
        self._max_turns = max_turns
        self._identity = identity
        self._permission_scope = permission_scope
        self._permission_ledger = permission_ledger
        self._limit_reached = False
        self.active_skills: dict[str, str] = {}
        self._skill_catalog = ""
        self._run_lock = asyncio.Lock()
        self._executor = ToolExecutor(
            registry,
            self._engine,
            self._permissions_enabled,
            self.runtime,
            broker=approval_broker,
            identity=identity,
            scope=permission_scope,
            ledger=permission_ledger,
        )

    def activate_skill(self, name: str, prompt_body: str) -> None:
        self.active_skills[name] = prompt_body

    def clear_active_skills(self) -> None:
        self.active_skills.clear()

    def set_skill_catalog(self, catalog: str) -> None:
        self._skill_catalog = catalog

    def _schedule_memory_update(
        self,
        user_text: str,
        assistant_text: str,
    ) -> None:
        manager = self._memory_manager
        if manager is None:
            return
        manager.schedule_extract(
            MemoryTurn(
                session_id=self.runtime.session.session_id,
                turn_id=uuid.uuid4().hex,
                user_text=user_text,
                assistant_text=assistant_text,
            )
        )
        manager.schedule_consolidation()

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
        return build_manage_input(
            conv=conv,
            provider=self._provider,
            model=self._provider.model,
            context_window=self.runtime.context_window,
            tool_defs=definitions,
            recovery=self.runtime.recovery,
            auto_tracking=self.runtime.auto_tracking,
            session=self.runtime.session,
            usage_anchor=self.runtime.usage_anchor,
            anchor_msg_len=self.runtime.anchor_msg_len,
            estimated_token=estimated,
            trigger=trigger,
        )

    def _apply_compaction(self, conv: Conversation, managed: ManageOutput) -> None:
        """把结构化压缩结果一次性持久化并替换内存历史。"""

        if managed.compaction is None:
            return
        result = managed.compaction
        conv.apply_compaction(
            CompactBoundary(result.summary, result.keep, int(time.time())),
            result.messages,
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
            self._apply_compaction(conv, output)
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

        current_user_text = next(
            (
                message.content
                for message in reversed(conv.messages())
                if message.role == "user"
            ),
            "",
        )
        recall_text = (
            await self._memory_manager.recall(current_user_text)
            if self._memory_manager is not None
            else ""
        )

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
        stable_system = build_system_prompt(self._instruction_text, memory_text)
        if self._instructions_content:
            stable_system = stable_system + "\n\n" + self._instructions_content

        unknown_run = 0
        self._limit_reached = False
        for iteration in range(1, self._max_turns + 1):
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
            self._apply_compaction(conv, managed)
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

            stream_state = StreamState()
            plan = ""
            if mode is Mode.PLAN:
                full = iteration == 1 or (iteration - 1) % PLAN_REMINDER_INTERVAL == 0
                plan = plan_reminder(full)
            deferred = deferred_tools_reminder(self._registry.get_deferred_tool_names())
            inbox_text = "\n\n".join(self.runtime.inbox.drain())
            reminder = combine_reminders(recall_text, plan, deferred, inbox_text)
            dynamic_environment = "\n\n".join(
                part
                for part in (
                    environment.render(),
                    self._skill_catalog,
                    render_active_skills(self.active_skills),
                )
                if part
            )
            system = System(
                stable=stable_system,
                environment=dynamic_environment,
            )
            async for event in stream_once(
                self._provider,
                Request(
                    messages=conv.messages(),
                    tools=definitions,
                    system=system,
                    reminder=reminder,
                ),
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
                    self._apply_compaction(conv, emergency)
                    self.runtime.usage_anchor = 0
                    self.runtime.anchor_msg_len = 0
                    if estimate_tokens(0, conv.messages(), 0) >= (
                        self.runtime.context_window - MANUAL_SAFETY_MARGIN
                    ):
                        yield AgentEvent(err=stream_error)
                        _ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                        return
                    stream_state = StreamState()
                    async for event in stream_once(
                        self._provider,
                        Request(
                            messages=conv.messages(),
                            tools=definitions,
                            system=system,
                            reminder=reminder,
                        ),
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
                if stream_state.text and current_user_text:
                    self._schedule_memory_update(current_user_text, stream_state.text)
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

            batch_state = BatchState(results=[None] * len(calls))
            try:
                async for event in self._executor.execute(
                    calls,
                    mode,
                    cancel,
                    batch_state,
                ):
                    yield event
            except asyncio.CancelledError:
                cancelled_results = [
                    result if result is not None else cancelled_result(calls[index])
                    for index, result in enumerate(batch_state.results)
                ]
                final_results = prepare_tool_results(
                    cancelled_results,
                    calls,
                    self.runtime.session,
                )
                conv.add_tool_results(final_results)
                _ensure_assistant_tail(conv, NOTICE_CANCELLED)
                raise
            results = [
                result if result is not None else cancelled_result(calls[index])
                for index, result in enumerate(batch_state.results)
            ]
            final_results = prepare_tool_results(
                results,
                calls,
                self.runtime.session,
            )
            conv.add_tool_results(final_results)

            if not batch_state.completed:
                _ensure_assistant_tail(conv, NOTICE_CANCELLED)
                return

            if unknown_run >= MAX_UNKNOWN_RUN:
                yield AgentEvent(notice=NOTICE_UNKNOWN_TOOLS)
                _ensure_assistant_tail(conv, NOTICE_UNKNOWN_TOOLS)
                yield AgentEvent(done=True)
                return

        self._limit_reached = True
        yield AgentEvent(notice=NOTICE_MAX_ITER)
        _ensure_assistant_tail(conv, NOTICE_MAX_ITER)
        yield AgentEvent(done=True)

    async def run_to_completion(
        self,
        conv: Conversation,
        task: str,
        mode: Mode = Mode.DEFAULT,
        cancel: asyncio.Event | None = None,
    ) -> RunResult:
        """追加任务后消费同一事件流，直到自然完成或到达轮数上限。"""

        if task:
            conv.add_user(task)
        cancel_event = cancel if cancel is not None else asyncio.Event()
        status = RunStatus.COMPLETED
        final_text = ""
        error: Exception | None = None
        usage = Usage()
        tool_count = 0
        last_activity = ""
        try:
            async for event in self.run(conv, mode, cancel_event):
                if event.text:
                    final_text = event.text
                if event.usage is not None:
                    usage = event.usage
                if event.tool is not None and event.tool.phase == Phase.END:
                    tool_count += 1
                    last_activity = event.tool.name
                if event.err is not None:
                    error = event.err
                if event.done:
                    break
        except asyncio.CancelledError:
            raise
        if self._limit_reached:
            status = RunStatus.LIMIT_REACHED
        elif error is not None:
            status = RunStatus.FAILED
        return RunResult(
            status=status,
            final_text=final_text,
            error=error,
            usage=usage,
            tool_count=tool_count,
            last_activity=last_activity,
        )


def new_agent(
    provider: Provider,
    registry: Registry,
    version: str,
    engine: Engine,
) -> Agent:
    """构造启用权限流水线的 Agent。"""

    return Agent(provider, registry, version, engine)
