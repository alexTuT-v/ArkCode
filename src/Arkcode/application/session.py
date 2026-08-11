"""会话级组合边界：显式持有当前 Provider、Agent、Conversation、Journal 与元数据。"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..subagents.approvals import ApprovalBroker
    from ..subagents.catalog import Catalog
    from ..subagents.launcher import SubAgentLauncher
    from ..subagents.manager import TaskManager

from ..agents import Agent, AgentEvent, SessionRuntime
from ..agents.identity import AgentIdentity, current_identity
from ..agents.parent import ParentContext, parent_scope
from ..config import Config, ProviderConfig, effective_context_window
from ..context import (
    CompactCircuitBreaker,
    RecoveryState,
    new_session_context,
    open_session_context,
)
from ..conversations import Conversation
from ..llm import Message, Provider, new_provider
from ..memory import Manager
from ..permissions import Engine, Mode
from ..prompts import render_skill_catalog
from ..sessions import (
    SessionInfo,
    SessionJournal,
    SessionMeta,
    SessionMetaStore,
    load_session,
)
from ..sessions.record import CompactBoundary
from ..skills import SkillExecutor, SkillLoader
from ..tools import Registry
from ..tools.workspace import ExecutionPathContext, workspace_scope

logger = logging.getLogger(__name__)


def _truncate_title(value: str) -> str:
    return value if len(value) <= 50 else value[:49] + "…"


class SessionSink:
    """把 Journal 持久化与 meta 更新合并为 Conversation 的显式 sink。"""

    def __init__(
        self,
        journal: SessionJournal,
        meta_store: SessionMetaStore,
        meta: SessionMeta,
    ) -> None:
        self.journal = journal
        self._meta_store = meta_store
        self._meta = meta
        self._lock = threading.RLock()
        self._dirty = False

    def _save(self) -> None:
        try:
            self._meta_store.save(self._meta)
            self._dirty = False
        except OSError:
            self._dirty = True
            logger.warning(
                "会话元数据更新失败，将在下次提交或关闭时重试",
                exc_info=True,
            )

    def _touch(self, *, message: Message | None = None) -> None:
        with self._lock:
            changes: dict[str, Any] = {"last_active": datetime.now().astimezone()}
            if message is not None:
                changes["message_count"] = self._meta.message_count + 1
                if (
                    not self._meta.title
                    and message.role == "user"
                    and message.content
                ):
                    changes["title"] = _truncate_title(message.content)
            self._meta = replace(self._meta, **changes)
            self._save()

    def append_message(self, message: Message) -> None:
        """先持久化消息，成功后才更新 meta。"""

        self.journal.append_message(message)
        self._touch(message=message)

    def append_boundary(self, boundary: CompactBoundary) -> None:
        """先持久化压缩边界，成功后才更新 meta 的活跃时间。"""

        self.journal.append_boundary(boundary)
        self._touch()

    def set_provider(self, provider: str, model: str) -> None:
        """更新 provider/model，不写入任何消息。"""

        with self._lock:
            self._meta = replace(
                self._meta,
                provider=provider,
                model=model,
                last_active=datetime.now().astimezone(),
            )
            self._save()

    def retry_dirty(self) -> None:
        if self._dirty:
            with self._lock:
                self._save()

    def close(self) -> None:
        self.retry_dirty()
        self.journal.close()


class SessionService:
    """进程内当前会话的显式所有权边界。"""

    def __init__(
        self,
        *,
        workspace: str | Path,
        version: str,
        registry: Registry,
        permissions: Engine | None,
        skills: SkillLoader,
        memory: Manager | None = None,
        instruction_text: str = "",
        memory_text: str = "",
        sessions_dir: str | None = None,
        mcp_instructions: str = "",
        runtime: SessionRuntime | None = None,
        journal: SessionJournal | None = None,
        config: Config | None = None,
        provider_configs: list[ProviderConfig] | None = None,
        task_manager: TaskManager | None = None,
        catalog: Catalog | None = None,
        approval_broker: ApprovalBroker | None = None,
        launcher: SubAgentLauncher | None = None,
        worktree_manager: object | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self._version = version
        self._registry = registry
        self._permissions = permissions
        self.skills = skills
        self._memory = memory
        self._instruction_text = instruction_text
        self._memory_text = memory_text
        self._mcp_instructions = mcp_instructions
        self._config = config
        self._provider_configs = list(provider_configs or [])
        self._provider_config: ProviderConfig | None = None
        self.task_manager: TaskManager | None = task_manager
        self.catalog: Catalog | None = catalog
        self.approval_broker: ApprovalBroker | None = approval_broker
        self.launcher: SubAgentLauncher | None = launcher
        self.worktree_manager = worktree_manager
        self.active_workspace: ExecutionPathContext | None = None
        self.runtime = runtime or SessionRuntime(
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context(str(self.workspace)),
        )
        self.journal = journal or SessionJournal(self.runtime.session.session_dir)
        self.meta_store = SessionMetaStore(self.runtime.session.session_dir)
        self._meta = SessionMeta.new(self.runtime.session.session_id)
        self.meta_store.save(self._meta)
        self.sink = SessionSink(self.journal, self.meta_store, self._meta)
        self.conversation = Conversation(sink=self.sink)
        self.sessions_dir = sessions_dir or str(
            Path(self.runtime.session.session_dir).parent
        )
        self.provider: Provider | None = None
        self.agent: Agent | None = None
        self.skill_executor: SkillExecutor | None = None
        self.mode = (
            self._permissions.start_mode()
            if self._permissions is not None
            else Mode.DEFAULT
        )
        self._cancel = asyncio.Event()
        self.skill_tasks: set[asyncio.Task[None]] = set()

    def activate_provider(self, config: ProviderConfig) -> None:
        """创建 Provider、Agent 与 SkillExecutor，并完成模型分配。"""

        provider = new_provider(config)
        self._provider_config = config
        if config not in self._provider_configs:
            self._provider_configs.append(config)
        self.sink.set_provider(config.name, provider.model)
        if self._memory is not None:
            self._memory.set_provider(provider, provider.model)
        self.runtime.context_window = effective_context_window(config)
        self.provider = provider
        self.agent = Agent(
            provider,
            self._registry,
            self._version,
            self._permissions,
            runtime=self.runtime,
            memory_manager=self._memory,
            instruction_text=(
                self._instruction_text
                + ("\n\n" + self._mcp_instructions if self._mcp_instructions else "")
            ),
            memory_text=self._memory_text,
        )
        self.skill_executor = SkillExecutor(
            self.agent,
            self.conversation,
            config,
            self._registry,
            self._permissions,
            self._version,
            self.workspace,
            launcher=self.launcher,
        )
        self.agent.set_skill_catalog(render_skill_catalog(self.skills.get_catalog()))
        self.mode = (
            self._permissions.start_mode()
            if self._permissions is not None
            else Mode.DEFAULT
        )

    async def submit_message(self, text: str) -> AsyncIterator[AgentEvent]:
        """把用户文本写入会话并运行 Agent，按事件流报告进度。"""

        agent = self.agent
        if agent is None:
            raise RuntimeError("Agent 尚未初始化")
        cancel = asyncio.Event()
        self._cancel = cancel
        self.conversation.add_user(text)
        try:
            execution_context = self.active_workspace or ExecutionPathContext.at(
                self.workspace
            )
            with workspace_scope(execution_context), parent_scope(
                self.parent_context()
            ):
                async for event in agent.run(self.conversation, self.mode, cancel):
                    yield event
        finally:
            if self._cancel is cancel:
                self._cancel = asyncio.Event()

    def parent_context(self) -> ParentContext:
        """构造当前主 Agent 的父会话快照，供 Agent/Job 工具使用。"""

        return ParentContext(
            workspace=self.workspace,
            conversation=self.conversation,
            identity=self._main_identity(),
            registry=self._registry,
            provider=self.provider,
            provider_config=self._provider_config,
            config=self._config,
        )

    def _main_identity(self) -> AgentIdentity:
        identity = current_identity()
        if identity.source != "main":
            return AgentIdentity.main(str(self.workspace))
        return identity

    def append_reminder(self, text: str) -> None:
        """把系统提醒注入主 Agent 的 ReminderInbox，下一轮模型请求自然读取。"""

        self.runtime.inbox.append(text)

    def set_active_workspace(self, context: ExecutionPathContext | None) -> None:
        """切换后续主 Agent Run 的显式路径上下文（不改变进程 cwd）。"""

        self.active_workspace = context

    async def force_compact(self) -> tuple[int, int]:
        """对当前会话执行一次手动压缩。"""

        agent = self.agent
        if agent is None:
            raise RuntimeError("压缩失败：尚未选择 provider")
        definitions = (
            self._registry.read_only_definitions()
            if self.mode is Mode.PLAN
            else self._registry.definitions()
        )
        return await agent.run_force_compact(self.conversation, definitions)

    def clear_session(self) -> None:
        """先构造完整的新会话 bundle，成功后再交换所有权并关闭旧 sink。"""

        context = new_session_context(str(self.workspace))
        journal = SessionJournal(context.session_dir)
        meta_store = SessionMetaStore(context.session_dir)
        meta = SessionMeta.new(context.session_id)
        meta_store.save(meta)
        sink = SessionSink(journal, meta_store, meta)
        conversation = Conversation(sink=sink)
        previous = self.sink
        self.journal = journal
        self.meta_store = meta_store
        self._meta = meta
        self.sink = sink
        self.conversation = conversation
        self.runtime.reset_for_new_session(context)
        if self.provider is not None:
            sink.set_provider(self.provider.name, self.provider.model)
        if self.agent is not None:
            self.agent.clear_active_skills()
        previous.close()

    def resume_session(self, info: SessionInfo) -> None:
        """恢复 format v2 会话；初始化过程不重新持久化消息。"""

        meta_store = SessionMetaStore(info.dir)
        meta = meta_store.load()
        if meta is None:
            raise ValueError(f"无法恢复非 format v2 会话: {info.id}")
        messages = load_session(info.dir)
        journal = SessionJournal(info.dir)
        sink = SessionSink(journal, meta_store, meta)
        if self.provider is not None:
            sink.set_provider(self.provider.name, self.provider.model)
        new_conversation = Conversation.from_messages(messages, sink=sink)
        new_context = open_session_context(str(self.workspace), info.id)
        old_sink = self.sink
        self.journal = journal
        self.meta_store = meta_store
        self._meta = meta
        self.sink = sink
        self.conversation = new_conversation
        self.runtime.session = new_context
        old_sink.close()

    def set_mode(self, mode: Mode) -> None:
        self.mode = mode

    @property
    def permissions(self) -> Engine | None:
        return self._permissions

    def clear_memory(self) -> None:
        if self._memory is not None:
            self._memory.clear()

    def cancel_turn(self) -> None:
        """置位当前轮次的取消事件。"""

        self._cancel.set()

    def track_skill_task(self, task: asyncio.Task[None]) -> None:
        """持有 fork 任务直到完成，避免悬空并支持退出取消。"""

        self.skill_tasks.add(task)
        task.add_done_callback(self.skill_tasks.discard)

    def close(self) -> None:
        """同步关闭当前 sink（重试脏 meta 并关闭 Journal）。"""

        self.sink.close()

    async def shutdown(self) -> None:
        """取消 Skill 后台任务并关闭当前 sink。"""

        pending = list(self.skill_tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.close()
