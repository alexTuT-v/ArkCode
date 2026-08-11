"""Team 协作工具：TeamCreate/Delete、Task* 与 SendMessage。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ..agents.identity import AgentIdentity, current_identity
from ..subagents.manager import TaskManager
from ..tools.base import Result, Tool
from .mailbox import Box
from .manager import TeamManager
from .models import BackendType, MessageType
from .protocol import ensure_request_id, new_message
from .shared_tasks import SharedTaskStore

if TYPE_CHECKING:
    from .models import Team


class TeamServices:
    """团队工具共享的依赖门面。"""

    def __init__(
        self,
        *,
        team_manager: TeamManager,
        task_manager: TaskManager,
        backend_factory: Callable[[BackendType], Any] | None = None,
    ) -> None:
        self.team_manager = team_manager
        self.task_manager = task_manager
        self._backend_factory = backend_factory

    def team_for(self, team_name: str) -> Team | None:
        return self.team_manager.get(team_name)

    def store(self, team: Team) -> SharedTaskStore:
        return SharedTaskStore(team.config_dir)

    def box(self, team: Team) -> Box:
        return Box(team.config_dir)

    def backend(self, backend_type: BackendType) -> Any:
        if self._backend_factory is not None:
            return self._backend_factory(backend_type)
        from .backends.inprocess import InProcessBackend
        from .backends.iterm2 import Iterm2Backend
        from .backends.tmux import TmuxBackend

        if backend_type is BackendType.TMUX:
            return TmuxBackend()
        if backend_type is BackendType.ITERM2:
            return Iterm2Backend()
        return InProcessBackend(self.task_manager)


class TeamCreateParams(BaseModel):
    team_name: str = Field(description="团队名")
    description: str = Field(default="", description="团队描述")
    agent_type: str = Field(default="", description="保留位")


class TeamCreateTool(Tool[TeamCreateParams]):
    read_only = False
    params_model = TeamCreateParams

    def __init__(self, services: TeamServices) -> None:
        self._services = services

    def name(self) -> str:
        return "TeamCreate"

    def description(self) -> str:
        return "创建一个 Team，当前 Agent 成为 Lead。"

    async def execute(self, params: TeamCreateParams) -> Result:
        team = await self._services.team_manager.create(
            params.team_name,
            params.agent_type,
        )
        return Result(
            json.dumps(
                {
                    "team_name": team.sanitized_name,
                    "backend": team.backend.value,
                    "config_path": str(team.config_path),
                },
                ensure_ascii=False,
            )
        )


class TeamDeleteParams(BaseModel):
    team_name: str = Field(description="团队名")
    force: bool = Field(default=False, description="忽略活跃队员强制删除")


class TeamDeleteTool(Tool[TeamDeleteParams]):
    read_only = False
    params_model = TeamDeleteParams

    def __init__(self, services: TeamServices) -> None:
        self._services = services

    def name(self) -> str:
        return "TeamDelete"

    def description(self) -> str:
        return "删除 Team；有活跃队员时需 force。"

    async def execute(self, params: TeamDeleteParams) -> Result:
        try:
            await self._services.team_manager.delete(
                params.team_name,
                params.force,
            )
        except Exception as exc:
            return Result(str(exc), is_error=True)
        return Result(json.dumps({"status": "deleted"}))


class TaskCreateParams(BaseModel):
    title: str = Field(description="任务标题")
    description: str = Field(default="", description="任务描述")
    assignee: str = Field(default="", description="队员名")
    blocked_by: list[str] = Field(default_factory=list, description="依赖的任务 id")


class TaskCreateTool(Tool[TaskCreateParams]):
    read_only = False
    params_model = TaskCreateParams

    def __init__(self, services: TeamServices) -> None:
        self._services = services

    def name(self) -> str:
        return "TaskCreate"

    def description(self) -> str:
        return "在团队任务板创建任务。"

    async def execute(self, params: TaskCreateParams) -> Result:
        team = self._identity_team()
        if team is None:
            return Result("当前不在任何 Team 中", is_error=True)
        task = await self._services.store(team).create(
            params.title,
            description=params.description,
            assignee=params.assignee,
            blocked_by=params.blocked_by,
        )
        return Result(json.dumps({"task_id": task.id}, ensure_ascii=False))

    def _identity_team(self) -> Team | None:
        identity: AgentIdentity = current_identity()
        if not identity.team_name:
            return None
        return self._services.team_for(identity.team_name)


class TaskGetParams(BaseModel):
    task_id: str = Field(description="任务 id")


class TaskGetTool(Tool[TaskGetParams]):
    read_only = True
    params_model = TaskGetParams

    def __init__(self, services: TeamServices) -> None:
        self._services = services

    def name(self) -> str:
        return "TaskGet"

    def description(self) -> str:
        return "返回团队任务详情。"

    async def execute(self, params: TaskGetParams) -> Result:
        team = self._team()
        if team is None:
            return Result("当前不在任何 Team 中", is_error=True)
        task = await self._services.store(team).get(params.task_id)
        if task is None:
            return Result(f"未知 task_id: {params.task_id}", is_error=True)
        return Result(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))

    def _team(self) -> Team | None:
        identity: AgentIdentity = current_identity()
        if not identity.team_name:
            return None
        return self._services.team_for(identity.team_name)


class TaskListParams(BaseModel):
    status: str | None = Field(default=None, description="按状态过滤")


class TaskListTool(Tool[TaskListParams]):
    read_only = True
    params_model = TaskListParams

    def __init__(self, services: TeamServices) -> None:
        self._services = services

    def name(self) -> str:
        return "TaskList"

    def description(self) -> str:
        return "列出团队任务，含依赖与 is_ready。"

    async def execute(self, params: TaskListParams) -> Result:
        identity: AgentIdentity = current_identity()
        if not identity.team_name:
            return Result("当前不在任何 Team 中", is_error=True)
        team = self._services.team_for(identity.team_name)
        if team is None:
            return Result("当前不在任何 Team 中", is_error=True)
        store = self._services.store(team)
        tasks = await store.list_tasks(params.status)
        payload = []
        for task in tasks:
            item = task.to_dict()
            item["is_ready"] = store.is_ready(task, tasks)
            payload.append(item)
        return Result(
            json.dumps({"tasks": payload}, ensure_ascii=False, indent=2)
        )


class TaskUpdateParams(BaseModel):
    task_id: str = Field(description="任务 id")
    title: str | None = Field(default=None)
    description: str | None = Field(default=None)
    status: str | None = Field(default=None)
    assignee: str | None = Field(default=None)
    add_blocks: list[str] = Field(default_factory=list)
    add_blocked_by: list[str] = Field(default_factory=list)
    remove_blocks: list[str] = Field(default_factory=list)
    remove_blocked_by: list[str] = Field(default_factory=list)


class TaskUpdateTool(Tool[TaskUpdateParams]):
    read_only = False
    params_model = TaskUpdateParams

    def __init__(self, services: TeamServices) -> None:
        self._services = services

    def name(self) -> str:
        return "TaskUpdate"

    def description(self) -> str:
        return "更新团队任务（含双向依赖）。"

    async def execute(self, params: TaskUpdateParams) -> Result:
        identity: AgentIdentity = current_identity()
        if not identity.team_name:
            return Result("当前不在任何 Team 中", is_error=True)
        team = self._services.team_for(identity.team_name)
        if team is None:
            return Result("当前不在任何 Team 中", is_error=True)
        fields: dict[str, object] = {}
        if params.title is not None:
            fields["title"] = params.title
        if params.description is not None:
            fields["description"] = params.description
        if params.status is not None:
            fields["status"] = params.status
        if params.assignee is not None:
            fields["assignee"] = params.assignee
        fields["add_blocks"] = params.add_blocks
        fields["add_blocked_by"] = params.add_blocked_by
        fields["remove_blocks"] = params.remove_blocks
        fields["remove_blocked_by"] = params.remove_blocked_by
        try:
            task = await self._services.store(team).update(
                params.task_id,
                **fields,
            )
        except Exception as exc:
            return Result(str(exc), is_error=True)
        return Result(json.dumps(task.to_dict(), ensure_ascii=False))


class SendMessageParams(BaseModel):
    to: str = Field(description="队员名 / agent_id / * 广播 / lead")
    content: str = Field(description="消息正文")
    type: str = Field(default="text", description="消息类型")
    request_id: str = Field(default="", description="结构化消息关联 id")
    approve: bool | None = Field(default=None, description="表态")


class SendMessageTool(Tool[SendMessageParams]):
    read_only = False
    params_model = SendMessageParams

    def __init__(self, services: TeamServices) -> None:
        self._services = services

    def name(self) -> str:
        return "SendMessage"

    def description(self) -> str:
        return "向 Team 成员发送消息（text/shutdown/plan_approval）。"

    async def execute(self, params: SendMessageParams) -> Result:
        identity = current_identity()
        try:
            message_type = MessageType(params.type)
        except ValueError:
            return Result(f"非法消息类型: {params.type}", is_error=True)
        message = ensure_request_id(
            new_message(
                identity.name or identity.agent_id,
                params.content,
                message_type=message_type,
                request_id=params.request_id,
                approve=params.approve,
            )
        )
        if (
            message_type is MessageType.PLAN_APPROVAL_RESPONSE
            and (not params.request_id or params.approve is None)
        ):
            return Result(
                "plan_approval_response 必须带 request_id 且 approve 非空",
                is_error=True,
            )

        team = self._resolve_team(params.to, identity)
        if team is None:
            return Result("找不到目标 Team", is_error=True)
        targets = await self._resolve_targets(team, params.to, identity)
        if not targets:
            return Result(f"无法解析收件人: {params.to}", is_error=True)
        box = self._services.box(team)
        for agent_id in targets:
            await box.write(agent_id, message)
            member = next(
                (item for item in team.members if item.agent_id == agent_id),
                None,
            )
            if member is not None:
                backend = self._services.backend(member.backend_type)
                await backend.wake(member.pane_id, member.agent_id)
                if member.backend_type is BackendType.IN_PROCESS:
                    job = self._services.task_manager.get(agent_id)
                    if job is not None and job.status.terminal:
                        await self._resume_inprocess(team, member, params.content)
        return Result(
            json.dumps(
                {
                    "delivered_to": targets,
                    "timestamp": message.timestamp,
                    "request_id": message.request_id,
                },
                ensure_ascii=False,
            )
        )

    def _resolve_team(
        self,
        to: str,
        identity: AgentIdentity,
    ) -> Team | None:
        if identity.team_name:
            return self._services.team_for(identity.team_name)
        resolved = self._services.team_manager.name_registry.resolve(to)
        if resolved is not None:
            for team in self._services.team_manager.list():
                if any(item.agent_id == resolved for item in team.members):
                    return team
        teams = self._services.team_manager.list()
        return teams[0] if teams else None

    async def _resolve_targets(
        self,
        team: Team,
        to: str,
        identity: AgentIdentity,
    ) -> list[str]:
        if to == "*":
            targets = [item.agent_id for item in team.members]
            if identity.source == "teammate" and team.lead_agent_id:
                targets.append(team.lead_agent_id)
            return targets
        if to == "lead":
            return [team.lead_agent_id] if team.lead_agent_id else []
        resolved = self._services.team_manager.name_registry.resolve(to)
        if resolved is not None:
            return [resolved]
        return [to]

    async def _resume_inprocess(
        self,
        team: Team,
        member: object,
        content: str,
    ) -> None:
        from .models import TeammateInfo

        if not isinstance(member, TeammateInfo):
            return
        await self._services.team_manager.set_member_active(
            team.sanitized_name,
            member.name,
            True,
        )
        try:
            self._services.task_manager.resume(member.name, content)
        except Exception:
            await self._services.team_manager.set_member_active(
                team.sanitized_name,
                member.name,
                False,
            )
