"""in-process 后端：复用 SubAgentLauncher/TaskManager。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from ...subagents.models import (
    BackgroundTask,
    CleanupReport,
    EnvironmentPreparer,
    PreparedEnvironment,
    RunResult,
)
from ...tools.workspace import ExecutionPathContext
from ..models import BackendType, SpawnRequest, SpawnResult

if TYPE_CHECKING:
    from ...subagents.manager import TaskManager


class _StaticWorkspacePreparer(EnvironmentPreparer):
    """把已由 Team 创建的 Worktree 固定为执行上下文。"""

    def __init__(self, workspace: ExecutionPathContext) -> None:
        self._workspace = workspace

    async def prepare(self, job: BackgroundTask) -> PreparedEnvironment:
        return PreparedEnvironment(workspace=self._workspace, reminder="")

    async def cleanup(
        self,
        job: BackgroundTask,
        outcome: RunResult | None,
    ) -> CleanupReport:
        return CleanupReport(kept=False)


class InProcessBackend:
    def __init__(
        self,
        task_manager: TaskManager | None = None,
        on_complete: Callable[[str, str, Any], Awaitable[None]] | None = None,
    ) -> None:
        self._task_manager = task_manager
        self._on_complete = on_complete

    def set_on_complete(
        self,
        callback: Callable[[str, str, Any], Awaitable[None]],
    ) -> None:
        self._on_complete = callback

    def type(self) -> BackendType:
        return BackendType.IN_PROCESS

    async def spawn(self, request: SpawnRequest) -> SpawnResult:
        if request.agent is None or request.conversation is None:
            raise RuntimeError("in-process spawn 需要 Agent 与 Conversation")
        if self._task_manager is None:
            raise RuntimeError("in-process 后端缺少 TaskManager")
        inner_agent = request.agent
        if self._on_complete is not None:
            callback = self._on_complete

            class _NotifyingAgent:
                async def run_to_completion(
                    self,
                    conv: object,
                    task: str,
                    mode: object,
                    cancel: object,
                ) -> Any:
                    result = await inner_agent.run_to_completion(  # type: ignore[attr-defined]
                        conv,
                        task,
                        mode,
                        cancel,
                    )
                    await callback(request.member_name, request.agent_id, result)
                    return result

            wrapped_agent: object = _NotifyingAgent()
        else:
            wrapped_agent = inner_agent
        workspace = ExecutionPathContext.at(request.worktree_path)
        job = BackgroundTask(
            id=request.agent_id,
            agent_id=request.agent_id,
            name=request.member_name,
            agent_type=request.agent_type,
            agent=wrapped_agent,  # type: ignore[arg-type]
            conversation=request.conversation,  # type: ignore[arg-type]
            task_text=request.initial_prompt,
            run_in_background=True,
            preparer=_StaticWorkspacePreparer(workspace),
        )
        self._task_manager.launch(job)
        return SpawnResult(
            pane_id="",
            agent_id=request.agent_id,
            backend=BackendType.IN_PROCESS,
        )

    async def wake(self, pane_id: str, agent_id: str) -> None:
        return None

    async def kill(self, pane_id: str, agent_id: str) -> None:
        if self._task_manager is not None:
            await self._task_manager.stop(agent_id)

    async def is_alive(self, pane_id: str, agent_id: str) -> bool:
        job = self._task_manager.get(agent_id) if self._task_manager else None
        return job is not None and not job.status.terminal
