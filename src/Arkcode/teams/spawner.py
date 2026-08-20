"""TeamSpawner：AgentTool 的 team_name 分支（预注册 + spawn + 回写）。"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..agents import Agent, SessionRuntime
from ..agents.identity import AgentIdentity, current_identity
from ..agents.parent import ParentContext
from ..context import (
    CompactCircuitBreaker,
    RecoveryState,
    new_session_context,
)
from ..conversations import Conversation
from ..permissions import Mode
from ..permissions.scope import PermissionLedger, PermissionScope
from ..subagents.catalog import unknown_type_message
from ..subagents.filter import RegistryPolicy, RegistryView
from ..subagents.launcher import AgentToolError, SubAgentLauncher
from ..subagents.manager import new_agent_id
from ..subagents.models import LaunchRequest
from ..tools.base import Result
from ..worktrees import WorktreeManager
from .manager import TeamManager
from .models import BackendType, SpawnRequest, TeammateInfo
from .protocol import new_message

TEAM_TOOL_NAMES = frozenset(
    {"TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "SendMessage"}
)

TEAM_INSTRUCTIONS_SUFFIX = (
    "\n\nIMPORTANT: You are running as an agent in a team.\n"
    "Just writing a response in text is not visible to others\n"
    "on your team - you MUST use the SendMessage tool.\n"
    "The user interacts primarily with the team lead.\n"
    "Your work is coordinated through the task system\n"
    "and teammate messaging."
)


class InProcessTeammateNoSpawnError(RuntimeError):
    pass


class TeamSpawner:
    def __init__(
        self,
        *,
        team_manager: TeamManager,
        worktree_manager: WorktreeManager,
        launcher: SubAgentLauncher,
        session_root: str | Path,
        backend_factory: Callable[[BackendType], object] | None = None,
    ) -> None:
        self._team_manager = team_manager
        self._wt_mgr = worktree_manager
        self._launcher = launcher
        self._session_root = Path(session_root)
        self._backend_factory = backend_factory

    def _backend(self, backend_type: BackendType) -> Any:
        if self._backend_factory is not None:
            return self._backend_factory(backend_type)
        from .backends.inprocess import InProcessBackend
        from .backends.iterm2 import Iterm2Backend
        from .backends.tmux import TmuxBackend

        if backend_type is BackendType.TMUX:
            return TmuxBackend()
        if backend_type is BackendType.ITERM2:
            return Iterm2Backend()
        return InProcessBackend(self._launcher._task_manager)

    async def spawn(
        self,
        request: LaunchRequest,
        parent: ParentContext,
    ) -> Result:
        team_name = request.team_name or ""
        team = self._team_manager.get(team_name)
        if team is None:
            return Result(f"未知 Team: {team_name}", is_error=True)
        identity = current_identity()
        if identity.source == "teammate":
            return Result(
                "in-process 队员不能再启动队员",
                is_error=True,
            )
        definition = None
        if request.subagent_type:
            definition = (
                self._launcher._catalog.resolve(request.subagent_type)
                if self._launcher._catalog is not None
                else None
            )
            if definition is None:
                return Result(
                    unknown_type_message(
                        self._launcher._catalog,
                        request.subagent_type,
                    ),
                    is_error=True,
                )
        else:
            definition = (
                self._launcher._catalog.resolve("general-purpose")
                if self._launcher._catalog is not None
                else None
            )
            if definition is None:
                return Result("缺少 general-purpose 内置角色", is_error=True)

        base_name = request.name or definition.name or "member"
        existing = {member.name for member in team.members}
        member_name = base_name
        suffix = 2
        while member_name in existing:
            member_name = f"{base_name}-{suffix}"
            suffix += 1
        agent_id = new_agent_id()
        worktree = await self._wt_mgr.create(
            f"team-{team.sanitized_name}/{member_name}",
            "HEAD",
            manual=False,
            owner_job_id=agent_id,
        )
        session_id = uuid.uuid4().hex[:12]
        session_dir = self._session_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        try:
            model_override = request.model or definition.model or "inherit"
            if parent.provider is None:
                raise AgentToolError("父 Provider 未初始化")
            provider = self._launcher._resolver.resolve(
                model_override,
                parent.provider,
            )
            runtime = SessionRuntime(
                recovery=RecoveryState(),
                auto_tracking=CompactCircuitBreaker(),
                session=new_session_context(str(session_dir)),
            )
            conversation = Conversation()
            teammate_identity = AgentIdentity(
                agent_id=agent_id,
                parent_id=identity.agent_id,
                trace_id=uuid.uuid4().hex[:12],
                agent_type=definition.name,
                name=member_name,
                source="teammate",
                team_name=team.sanitized_name,
            )
            allowed: frozenset[str] | None = None
            if definition.tools:
                allowed = frozenset(
                    set(definition.tools) | TEAM_TOOL_NAMES | {"Agent"}
                )
            policy = RegistryPolicy(
                globally_denied=frozenset(),
                allowed=allowed,
                denied=frozenset(definition.disallowed_tools),
                background_allowed=None,
                keep_agent_schema=True,
            )
            view = RegistryView.from_parent(
                parent.registry,
                policy,
                copy_discovery=False,
            )
            ledger = PermissionLedger()
            scope = PermissionScope.subagent_instance(agent_id)
            mode = (
                Mode.PLAN
                if (request.plan_mode_required or definition.plan_mode_required)
                else Mode.DONT_ASK
            )
            engine = (
                self._launcher._engine.child(scope, ledger, mode)
                if self._launcher._engine is not None
                else None
            )
            agent = Agent(
                provider,
                view,
                self._launcher._version,
                engine,
                runtime=runtime,
                instructions_content=(
                    definition.instructions_content + TEAM_INSTRUCTIONS_SUFFIX
                ),
                max_turns=definition.max_turns,
                identity=teammate_identity,
                permission_scope=scope,
                permission_ledger=ledger,
                approval_broker=self._launcher._broker,
            )
            runtime.inbox.append(
                "<team-context>\n"
                f"team: {team.sanitized_name}\n"
                f"你的成员名: {member_name}\n"
                f"你的 agent_id: {agent_id}\n"
                f"worktree 目录: {worktree.path}\n"
                "</team-context>"
            )

            member = TeammateInfo(
                name=member_name,
                agent_id=agent_id,
                agent_type=definition.name,
                model=model_override if model_override != "inherit" else "",
                worktree_path=str(worktree.path),
                branch=worktree.branch,
                backend_type=team.backend,
                pane_id="",
                is_active=True,
                plan_mode_required=bool(
                    request.plan_mode_required or definition.plan_mode_required
                ),
                session_dir=str(session_dir),
            )
            self._team_manager.name_registry.register(member_name, agent_id)
            await self._team_manager.add_member(team.sanitized_name, member)

            from .mailbox import Box

            box = Box(team.config_dir)
            spawn_request = SpawnRequest(
                team_name=team.sanitized_name,
                member_name=member_name,
                agent_id=agent_id,
                worktree_path=str(worktree.path),
                session_dir=str(session_dir),
                agent_type=definition.name,
                model=model_override if model_override != "inherit" else "",
                initial_prompt=request.prompt,
                plan_mode_required=member.plan_mode_required,
                agent=agent,
                conversation=conversation,
            )
            if team.backend is not BackendType.IN_PROCESS:
                await box.write(
                    agent_id,
                    new_message("lead", request.prompt),
                )
            backend = self._backend(team.backend)
            from .backends.inprocess import InProcessBackend

            if isinstance(backend, InProcessBackend):
                box_for_idle = Box(team.config_dir)

                async def notify_idle(
                    member: str,
                    agent: str,
                    result: object,
                ) -> None:
                    try:
                        await self._team_manager.set_member_active(
                            team.sanitized_name,
                            member,
                            False,
                        )
                    except Exception:
                        pass
                    await box_for_idle.write(
                        team.lead_agent_id,
                        new_message(
                            member,
                            f"[idle] {member} (reason: available)",
                        ),
                    )

                backend.set_on_complete(notify_idle)
            result = await backend.spawn(spawn_request)
            await self._team_manager.update_member(
                team.sanitized_name,
                member_name,
                pane_id=result.pane_id,
                backend_type=result.backend,
                is_active=True,
            )
            return Result(
                json.dumps(
                    {
                        "member_name": member_name,
                        "agent_id": agent_id,
                        "worktree": str(worktree.path),
                        "backend": result.backend.value,
                        "pane_id": result.pane_id,
                    },
                    ensure_ascii=False,
                )
            )
        except Exception:
            await self._rollback_spawn(team.sanitized_name, member_name, agent_id)
            raise

    async def _rollback_spawn(
        self,
        team_name: str,
        member_name: str,
        agent_id: str,
    ) -> None:
        self._team_manager.name_registry.unregister(member_name)
        try:
            await self._team_manager.remove_member(team_name, member_name)
        except Exception:
            pass
        try:
            worktree = next(
                (
                    item
                    for item in self._wt_mgr.list()
                    if item.owner_job_id == agent_id
                ),
                None,
            )
            if worktree is not None:
                from ..worktrees import ExitOptions

                await self._wt_mgr.remove(
                    worktree.name,
                    ExitOptions(discard_changes=True),
                )
        except Exception:
            pass
