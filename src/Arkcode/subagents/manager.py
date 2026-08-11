"""Job 生命周期管理（内部 TaskManager/BackgroundTask，对外 Job 语义）。"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from ..agents import Agent, SessionRuntime
from ..agents.events import RunResult
from ..agents.identity import AgentIdentity
from ..conversations import Conversation
from ..permissions import Mode
from ..tools.workspace import workspace_scope
from .models import (
    BackgroundTask,
    EnvironmentPreparer,
    JobStatus,
    status_from_run,
)

AUTO_BACKGROUND_SECONDS = 120.0


@dataclass(slots=True)
class ExecutionHandle:
    """adopt_running 的输入：一段已在执行的子 Agent 运行。"""

    task_text: str
    agent: Agent
    conversation: Conversation
    mode: Mode = Mode.DEFAULT
    name: str = ""
    agent_type: str = ""
    run_in_background: bool = True
    identity: AgentIdentity | None = None
    runtime: SessionRuntime | None = None
    preparer: EnvironmentPreparer | None = None


class TaskManager:
    """登记、运行、查询与停止所有 Job（前台与后台同一状态机）。"""

    def __init__(self) -> None:
        self._jobs: dict[str, BackgroundTask] = {}
        self._by_name: dict[str, str] = {}
        self._done: asyncio.Queue[str] = asyncio.Queue()
        self._shutdown = False

    def launch(self, job: BackgroundTask) -> str:
        if self._shutdown:
            raise RuntimeError("TaskManager 已关闭，无法启动新 Job")
        if job.id in self._jobs:
            raise ValueError(f"Job 已存在: {job.id}")
        self._jobs[job.id] = job
        if job.name:
            self._by_name[job.name] = job.id
        job.start_time = time.time()
        job.status = (
            JobStatus.PREPARING
            if job.preparer is not None
            else JobStatus.RUNNING
        )
        job.task = asyncio.create_task(self._run(job))
        return job.id

    async def _run(self, job: BackgroundTask) -> RunResult | None:
        environment = None
        task_text = job.task_text
        try:
            if job.preparer is not None:
                environment = await job.preparer.prepare(job)
                if environment.reminder:
                    task_text = f"{environment.reminder}\n\n{task_text}"
                job.status = JobStatus.RUNNING
            if environment is not None:
                with workspace_scope(environment.workspace):
                    result = await job.agent.run_to_completion(
                        job.conversation,
                        task_text,
                        job.mode,
                        job.cancel_event,
                    )
            else:
                result = await job.agent.run_to_completion(
                    job.conversation,
                    task_text,
                    job.mode,
                    job.cancel_event,
                )
            job.final_result = result
            job.status = status_from_run(result.status)
            job.result = result.final_text
            job.error = result.error
            job.usage = result.usage
            job.tool_count = result.tool_count
            job.last_activity = result.last_activity
            return result
        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            job.result = "（任务已取消。）"
            return None
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = exc
            job.result = f"任务失败: {exc}"
            return None
        finally:
            if job.preparer is not None and environment is not None:
                try:
                    report = await job.preparer.cleanup(job, job.final_result)
                    if report.kept:
                        suffix = (
                            f"\n[Worktree 保留在 {report.path},"
                            f"分支 {report.branch},base {report.base_commit}]"
                        )
                        job.result = (job.result or "") + suffix
                except Exception:
                    # 清理失败不能掩盖终态。
                    pass
            job.end_time = time.time()
            self._finish(job)

    def _finish(self, job: BackgroundTask) -> None:
        if job.status not in {
            JobStatus.COMPLETED,
            JobStatus.LIMIT_REACHED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }:
            return
        if job.run_in_background:
            self._done.put_nowait(job.id)

    async def wait_foreground(
        self,
        job_id: str,
        timeout: float,
    ) -> RunResult | None:
        """以 shield 等待前台 Job；超时或转后台时返回 None。"""

        job = self._jobs.get(job_id)
        if job is None or job.task is None:
            raise KeyError(f"未知 Job: {job_id}")
        job.foreground = True
        completion = asyncio.shield(job.task)
        timer = asyncio.create_task(asyncio.sleep(timeout))
        backgrounded = asyncio.create_task(job.backgrounded_event.wait())
        try:
            done, _ = await asyncio.wait(
                {completion, timer, backgrounded},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if completion in done:
                result = completion.result()
                assert result is None or isinstance(result, RunResult)
                return result
            return None
        finally:
            for pending in (completion, timer, backgrounded):
                pending.cancel()
            await asyncio.gather(
                completion,
                timer,
                backgrounded,
                return_exceptions=True,
            )

    def move_to_background(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status.terminal:
            return False
        job.run_in_background = True
        job.foreground = False
        job.backgrounded_event.set()
        return True

    def move_foreground_to_background(self) -> str | None:
        """ESC 路径：把唯一前台运行中的 Job 切到后台。"""

        for job in self._jobs.values():
            if job.foreground and not job.status.terminal:
                self.move_to_background(job.id)
                return job.id
        return None

    def adopt_running(self, handle: ExecutionHandle) -> BackgroundTask:
        job = BackgroundTask(
            id=new_job_id(),
            agent_id=(
                handle.identity.agent_id
                if handle.identity is not None
                else f"agent-{uuid.uuid4().hex[:7]}"
            ),
            name=handle.name,
            agent_type=handle.agent_type,
            agent=handle.agent,
            conversation=handle.conversation,
            task_text=handle.task_text,
            run_in_background=handle.run_in_background,
            mode=handle.mode,
            identity=handle.identity,
            runtime=handle.runtime,
            preparer=handle.preparer,
        )
        self.launch(job)
        return job

    def get(self, job_id: str) -> BackgroundTask | None:
        return self._jobs.get(job_id)

    def list(self) -> list[BackgroundTask]:
        return [job for job in self._jobs.values()]

    async def stop(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status.terminal:
            return False
        job.cancel_event.set()
        if job.task is not None and not job.task.done():
            job.task.cancel()
        return True

    def resume(self, agent_ref: str, message: str) -> BackgroundTask:
        """按 name（或 job_id）续派已终止的 Agent，复用原上下文。"""

        target = self._by_name.get(agent_ref) or agent_ref
        job = self._jobs.get(target)
        if job is None:
            raise KeyError(f"找不到可续派的 Agent: {agent_ref}")
        if not job.status.terminal:
            raise RuntimeError("运行中的 Agent 不允许重入")
        new_job = BackgroundTask(
            id=new_job_id(),
            agent_id=job.agent_id,
            name=job.name,
            agent_type=job.agent_type,
            agent=job.agent,
            conversation=job.conversation,
            task_text=message,
            run_in_background=True,
            mode=job.mode,
            identity=job.identity,
            runtime=job.runtime,
            preparer=job.preparer,
        )
        self.launch(new_job)
        return new_job

    def subscribe_done(self) -> asyncio.Queue[str]:
        return self._done

    async def shutdown(self) -> None:
        self._shutdown = True
        tasks = [
            job.task for job in self._jobs.values() if job.task is not None
        ]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for job in self._jobs.values():
            if not job.status.terminal:
                job.status = JobStatus.CANCELLED


def new_job_id() -> str:
    return f"job-{uuid.uuid4().hex[:8]}"


def new_agent_id() -> str:
    return f"agent-{uuid.uuid4().hex[:7]}"
