"""定义式、Fork、Skill fork 与 in-process teammate 的统一启动入口。"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from ..agents import Agent, SessionRuntime
from ..agents.identity import AgentIdentity
from ..agents.parent import ParentContext
from ..config import ProviderConfig
from ..context import (
    CompactCircuitBreaker,
    RecoveryState,
    new_session_context,
)
from ..conversations import Conversation
from ..llm import Message, Provider, new_provider
from ..permissions import Engine, Mode, parse_mode
from ..permissions.scope import PermissionLedger, PermissionScope
from .approvals import ApprovalBroker
from .catalog import Catalog, unknown_type_message
from .filter import RegistryView, build_policy
from .fork import build_forked_messages
from .manager import (
    AUTO_BACKGROUND_SECONDS,
    TaskManager,
    new_agent_id,
    new_job_id,
)
from .models import (
    BackgroundTask,
    EnvironmentPreparer,
    LaunchOutcome,
    LaunchRequest,
)


class AgentToolError(RuntimeError):
    """Agent 工具启动失败的结构化错误。"""


class ProviderResolver(Protocol):
    def resolve(self, model: str, parent: Provider) -> Provider: ...


class DefaultProviderResolver:
    """inherit 返回父 Provider；否则按配置名匹配或复制父配置覆盖 model。"""

    def __init__(
        self,
        configs: list[ProviderConfig],
        parent_config: ProviderConfig | None,
    ) -> None:
        self._configs = list(configs)
        self._parent_config = parent_config

    def resolve(self, model: str, parent: Provider) -> Provider:
        if not model or model == "inherit":
            return parent
        for config in self._configs:
            if config.name == model:
                return new_provider(config)
        if self._parent_config is not None:
            return new_provider(
                self._parent_config.model_copy(update={"model": model})
            )
        return parent


class SubAgentLauncher:
    """统一装配 Provider/RegistryView/Engine.child/Runtime/Conversation/Identity。"""

    def __init__(
        self,
        *,
        catalog: Catalog | None,
        task_manager: TaskManager,
        broker: ApprovalBroker,
        engine: Engine | None,
        version: str,
        workspace: str | Path,
        providers: list[ProviderConfig] | None = None,
        parent_config: ProviderConfig | None = None,
        enable_background: bool = True,
        worktree_preparer_factory: Callable[[], EnvironmentPreparer | None]
        | None = None,
    ) -> None:
        self._catalog = catalog
        self._task_manager = task_manager
        self._broker = broker
        self._engine = engine
        self._version = version
        self._workspace = Path(workspace)
        self._resolver = DefaultProviderResolver(providers or [], parent_config)
        self._enable_background = enable_background
        self._worktree_preparer_factory = worktree_preparer_factory

    def _background_allowed(self) -> bool:
        if callable(self._enable_background):
            return bool(self._enable_background())
        return bool(self._enable_background)

    async def launch(
        self,
        request: LaunchRequest,
        parent: ParentContext,
    ) -> LaunchOutcome:
        is_fork = not request.subagent_type
        if is_fork and not self._background_allowed():
            raise AgentToolError("后台禁用，无法 Fork")
        definition = None
        if not is_fork:
            assert request.subagent_type is not None
            definition = (
                self._catalog.resolve(request.subagent_type)
                if self._catalog is not None
                else None
            )
            if definition is None:
                raise AgentToolError(
                    unknown_type_message(self._catalog, request.subagent_type)
                )
        background = (
            request.run_in_background
            or (definition.background if definition is not None else False)
            or is_fork
        )
        if not self._background_allowed():
            background = False
        return await self._build_and_launch(
            request,
            parent,
            definition,
            background,
            is_fork,
        )

    async def launch_fork(
        self,
        request: LaunchRequest,
        parent: ParentContext,
        *,
        base_messages: Sequence[Message] | None = None,
        run_in_background: bool = False,
    ) -> LaunchOutcome:
        return await self._build_and_launch(
            request,
            parent,
            None,
            run_in_background,
            True,
            base_messages=base_messages,
        )

    async def _build_and_launch(
        self,
        request: LaunchRequest,
        parent: ParentContext,
        definition: object | None,
        background: bool,
        is_fork: bool,
        *,
        base_messages: Sequence[Message] | None = None,
    ) -> LaunchOutcome:
        agent_type = (
            getattr(definition, "name", "")
            if definition is not None
            else ("fork" if is_fork else "")
        )
        agent_id = new_agent_id()
        identity = AgentIdentity(
            agent_id=agent_id,
            parent_id=parent.identity.agent_id,
            trace_id=uuid.uuid4().hex[:12],
            agent_type=agent_type,
            name=request.name or agent_type or "fork",
            source="fork" if is_fork else "defined",
            team_name=request.team_name or "",
        )
        permission_mode = (
            getattr(definition, "permission_mode", "default")
            if definition is not None
            else "default"
        )
        parsed_mode, ok = parse_mode(permission_mode)
        mode = parsed_mode if ok else Mode.DEFAULT
        if request.plan_mode_required:
            mode = Mode.PLAN
        model_override = (
            request.model
            or (getattr(definition, "model", "") if definition is not None else "")
            or "inherit"
        )
        if parent.provider is None:
            raise AgentToolError("父 Provider 未初始化，无法启动子 Agent")
        provider = self._resolver.resolve(model_override, parent.provider)

        runtime = SessionRuntime(
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context(str(parent.workspace)),
        )
        if is_fork:
            if base_messages is not None:
                messages = build_forked_messages(base_messages, request.prompt)
            else:
                messages = build_forked_messages(parent.conversation, request.prompt)
            conversation = Conversation.from_messages(messages)
        else:
            conversation = Conversation()

        policy = build_policy(
            tools=(
                getattr(definition, "tools", ())
                if definition is not None
                else ()
            ),
            disallowed_tools=(
                getattr(definition, "disallowed_tools", ())
                if definition is not None
                else ()
            ),
            background=background,
            fork=is_fork,
        )
        view = RegistryView.from_parent(
            parent.registry,
            policy,
            copy_discovery=is_fork,
        )
        ledger = PermissionLedger()
        scope = PermissionScope.subagent_type(agent_type or "fork")
        engine = (
            self._engine.child(scope, ledger, mode)
            if self._engine is not None
            else None
        )
        agent = Agent(
            provider,
            view,
            self._version,
            engine,
            runtime=runtime,
            instructions_content=(
                getattr(definition, "instructions_content", "")
                if definition is not None
                else ""
            ),
            max_turns=(
                getattr(definition, "max_turns", 25)
                if definition is not None
                else 25
            ),
            identity=identity,
            permission_scope=scope,
            permission_ledger=ledger,
            approval_broker=self._broker,
        )
        preparer: EnvironmentPreparer | None = None
        if (
            definition is not None
            and getattr(definition, "isolation", "") == "worktree"
            and self._worktree_preparer_factory is not None
        ):
            preparer = self._worktree_preparer_factory()
        job = BackgroundTask(
            id=new_job_id(),
            agent_id=agent_id,
            name=request.name or "",
            agent_type=agent_type,
            agent=agent,
            conversation=conversation,
            task_text="" if is_fork else request.prompt,
            run_in_background=background,
            mode=mode,
            identity=identity,
            runtime=runtime,
            preparer=preparer,
        )
        self._task_manager.launch(job)
        if background:
            return LaunchOutcome(job_id=job.id, status="async_launched")
        result = await self._task_manager.wait_foreground(
            job.id,
            AUTO_BACKGROUND_SECONDS,
        )
        if result is None:
            if job.status.terminal:
                return LaunchOutcome(
                    job_id=job.id,
                    status=job.status.value,
                    final_text=job.result,
                )
            if job.backgrounded_event.is_set():
                return LaunchOutcome(
                    job_id=job.id,
                    status="backgrounded_by_user",
                )
            return LaunchOutcome(
                job_id=job.id,
                status="timed_out_to_background",
            )
        return LaunchOutcome(
            job_id=job.id,
            status=result.status.value,
            final_text=result.final_text,
        )
