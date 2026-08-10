"""工具批执行、权限检查、审批等待与结果事件。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..llm import ToolCall, ToolResult
from ..permissions import Decision, Engine, Mode, Outcome
from ..tools import DEFAULT_TIMEOUT, Registry
from .events import NOTICE_CANCELLED, AgentEvent, ApprovalRequest, Phase, ToolEvent
from .runtime import SessionRuntime


@dataclass
class BatchState:
    """一次工具批执行累积出的状态。"""

    results: list[ToolResult | None]
    completed: bool = True


def _args_preview(call: ToolCall) -> str:
    value = call.input or "{}"
    return value if len(value) <= 80 else value[:77] + "..."


def cancelled_result(call: ToolCall) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        content=NOTICE_CANCELLED,
        is_error=True,
    )


class ToolExecutor:
    """按权限策略并发或串行执行一批工具调用。"""

    def __init__(
        self,
        registry: Registry,
        engine: Engine | None,
        permissions_enabled: bool,
        runtime: SessionRuntime,
    ) -> None:
        self._registry = registry
        self._engine = engine
        self._permissions_enabled = permissions_enabled
        self._runtime = runtime

    def _check_permission(
        self,
        mode: Mode,
        call: ToolCall,
        read_only: bool,
    ) -> tuple[Decision, str]:
        if mode is Mode.PLAN and not read_only:
            return Decision.DENY, "Plan Mode 不允许执行有副作用的工具"
        if not self._permissions_enabled:
            return Decision.ALLOW, ""
        assert self._engine is not None
        return self._engine.check(mode, call, read_only)

    async def execute(
        self,
        calls: list[ToolCall],
        mode: Mode,
        cancel: asyncio.Event,
        state: BatchState,
    ) -> AsyncIterator[AgentEvent]:
        """按模型顺序执行工具批，保持只读并发与副作用串行。"""

        index = 0
        while index < len(calls):
            if cancel.is_set():
                state.completed = False
                for remaining in range(index, len(calls)):
                    state.results[remaining] = cancelled_result(calls[remaining])
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
                    state.results[remaining] = cancelled_result(calls[remaining])
                return
            index = end

    async def _run_batch(
        self,
        calls: list[ToolCall],
        indexes: range,
        state: BatchState,
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
                state.results[index] = cancelled_result(calls[index])
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
                        self._runtime.recovery.record_file(
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
                        state.results[index] = cancelled_result(call)
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
                        assert self._engine is not None
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
                result = cancelled_result(call)
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
