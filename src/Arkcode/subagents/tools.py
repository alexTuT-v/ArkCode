"""Agent 与 Job 编排工具。

模型可见名：Agent / JobList / JobGet / JobStop / JobSend。
"""

from __future__ import annotations

import json
from typing import Any, cast

from pydantic import BaseModel, Field

from ..agents.identity import current_identity
from ..agents.parent import current_parent
from ..tools.base import Result, Tool
from .fork import AgentLaunchBlocked, assert_can_launch_agent
from .launcher import AgentToolError, SubAgentLauncher
from .manager import TaskManager
from .models import LaunchRequest


class AgentParams(BaseModel):
    prompt: str = Field(description="交给子 Agent 的任务指令")
    description: str = Field(description="一句话描述任务，供 UI 展示")
    subagent_type: str | None = Field(
        default=None,
        description="预定义角色名；留空走 Fork 路径",
    )
    model: str | None = Field(
        default=None,
        description="模型覆盖：haiku/sonnet/opus/inherit 或已配置 provider 名",
    )
    run_in_background: bool = Field(default=False, description="true 时强制后台启动")
    name: str | None = Field(default=None, description="命名本次启动，供 JobSend 使用")
    team_name: str | None = Field(
        default=None,
        description="非空时作为队员加入团队",
    )


class AgentTool(Tool[AgentParams]):
    """主 Agent 启动子 Agent 的统一入口。"""

    read_only = False
    params_model = AgentParams

    def __init__(
        self,
        launcher: SubAgentLauncher,
        *,
        team_spawner: Any | None = None,
    ) -> None:
        self._launcher = launcher
        self._team_spawner = team_spawner

    def name(self) -> str:
        return "Agent"

    def description(self) -> str:
        return (
            "启动一个子 Agent 完成独立任务。subagent_type 指定预定义角色；"
            "留空走 Fork 路径（继承当前对话历史）。team_name 非空时作为队员加入团队。"
        )

    async def execute(self, params: AgentParams) -> Result:
        parent = current_parent()
        if parent is None:
            return Result("缺少父会话上下文，无法启动子 Agent", is_error=True)
        try:
            assert_can_launch_agent(current_identity(), parent.conversation.messages())
        except AgentLaunchBlocked as exc:
            return Result(str(exc), is_error=True)
        request = LaunchRequest(
            prompt=params.prompt,
            description=params.description,
            subagent_type=params.subagent_type,
            model=params.model,
            run_in_background=params.run_in_background,
            name=params.name,
            team_name=params.team_name,
        )
        if params.team_name:
            if self._team_spawner is None:
                return Result("Team 功能未启用", is_error=True)
            return cast(
                Result,
                await self._team_spawner.spawn(request, parent),
            )
        try:
            outcome = await self._launcher.launch(request, parent)
        except AgentToolError as exc:
            return Result(str(exc), is_error=True)
        if outcome.status in {
            "async_launched",
            "timed_out_to_background",
            "backgrounded_by_user",
        }:
            return Result(
                json.dumps(
                    {"job_id": outcome.job_id, "status": outcome.status},
                    ensure_ascii=False,
                )
            )
        return Result(outcome.final_text or f"（{outcome.status}）")


class JobListParams(BaseModel):
    pass


class JobListTool(Tool[JobListParams]):
    """列出当前仍保留的执行实例。"""

    read_only = True
    params_model = JobListParams

    def __init__(self, manager: TaskManager) -> None:
        self._manager = manager

    def name(self) -> str:
        return "JobList"

    def description(self) -> str:
        return (
            "列出当前所有 Job 的简要状态"
            "（job_id、name、status、tool_count、last_activity）。"
        )

    async def execute(self, params: JobListParams) -> Result:
        rows = [
            (
                f"{job.id}  {job.name or '-'}  {job.status.value}  "
                f"tools={job.tool_count}  last={job.last_activity or '-'}"
            )
            for job in self._manager.list()
        ]
        return Result("\n".join(rows) if rows else "（无 Job）")


class JobGetParams(BaseModel):
    job_id: str = Field(description="要查询的 job_id")


class JobGetTool(Tool[JobGetParams]):
    """返回单个 Job 的完整状态。"""

    read_only = True
    params_model = JobGetParams

    def __init__(self, manager: TaskManager) -> None:
        self._manager = manager

    def name(self) -> str:
        return "JobGet"

    def description(self) -> str:
        return "返回指定 Job 的完整状态（含结果、错误、usage 与 worktree 信息）。"

    async def execute(self, params: JobGetParams) -> Result:
        job = self._manager.get(params.job_id)
        if job is None:
            return Result(f"未知 job_id: {params.job_id}", is_error=True)
        payload = {
            "job_id": job.id,
            "name": job.name,
            "status": job.status.value,
            "result": job.result,
            "error": str(job.error) if job.error is not None else "",
            "tool_count": job.tool_count,
            "last_activity": job.last_activity,
            "usage": {
                "input": job.usage.input,
                "output": job.usage.output,
            },
            "worktree": {
                "name": job.worktree_name,
                "path": job.worktree_path,
                "branch": job.worktree_branch,
                "base_commit": job.worktree_base_commit,
            },
        }
        return Result(json.dumps(payload, ensure_ascii=False, indent=2))


class JobStopParams(BaseModel):
    job_id: str = Field(description="要停止的 job_id")


class JobStopTool(Tool[JobStopParams]):
    """取消指定 Job。"""

    read_only = False
    params_model = JobStopParams

    def __init__(self, manager: TaskManager) -> None:
        self._manager = manager

    def name(self) -> str:
        return "JobStop"

    def description(self) -> str:
        return "取消指定 Job，返回 cancellation_requested。"

    async def execute(self, params: JobStopParams) -> Result:
        await self._manager.stop(params.job_id)
        return Result(json.dumps({"status": "cancellation_requested"}))


class JobSendParams(BaseModel):
    name: str = Field(description="已结束且上下文保留的 Agent 名称")
    message: str = Field(description="续派的新任务")


class JobSendTool(Tool[JobSendParams]):
    """向已结束的 SubAgent 续派新任务。"""

    read_only = False
    params_model = JobSendParams

    def __init__(self, manager: TaskManager) -> None:
        self._manager = manager

    def name(self) -> str:
        return "JobSend"

    def description(self) -> str:
        return "按 name 复用已结束的 SubAgent 上下文续派新任务，创建新 job_id。"

    async def execute(self, params: JobSendParams) -> Result:
        try:
            job = self._manager.resume(params.name, params.message)
        except (KeyError, RuntimeError) as exc:
            return Result(str(exc), is_error=True)
        return Result(
            json.dumps(
                {"job_id": job.id, "status": "async_launched"},
                ensure_ascii=False,
            )
        )
