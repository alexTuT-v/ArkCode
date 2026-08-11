"""--team-member 的 Pane worker 自治循环。"""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..agents import Agent, SessionRuntime
from ..agents.identity import AgentIdentity
from ..config import load
from ..context import (
    CompactCircuitBreaker,
    RecoveryState,
    open_session_context,
)
from ..conversations import Conversation
from ..llm import new_provider
from ..permissions import Mode, new_engine
from ..permissions.scope import PermissionLedger, PermissionScope
from ..sessions import load_session
from ..tools import new_default_registry
from .mailbox import Box
from .manager import TeamManager
from .models import MessageType
from .protocol import new_message


class TeamMemberLoop:
    """消费 mailbox、执行任务、通知 idle 与处理 Plan 审批。"""

    def __init__(
        self,
        *,
        member_name: str,
        agent_id: str,
        team_name: str,
        lead_agent_id: str,
        box: Box,
        agent: Agent,
        conversation: Conversation,
        team_manager: TeamManager | None = None,
        plan_mode_required: bool = False,
        mailbox_dir: Path | None = None,
    ) -> None:
        self._member_name = member_name
        self._agent_id = agent_id
        self._team_name = team_name
        self._lead_agent_id = lead_agent_id
        self._box = box
        self._agent = agent
        self._conversation = conversation
        self._team_manager = team_manager
        self._plan_mode_required = plan_mode_required
        self._mailbox_dir = mailbox_dir
        self._wake = asyncio.Event()
        self._mode = Mode.PLAN if plan_mode_required else Mode.DONT_ASK
        self._last_result: object | None = None
        self.turns = 0

    def wake(self) -> None:
        self._wake.set()

    async def run(self) -> int:
        awaiting_plan: str = ""
        while True:
            if self._mailbox_dir is not None and not self._mailbox_dir.exists():
                return 0
            messages = await self._box.read(self._agent_id)
            unread_indexes = [
                index for index, message in enumerate(messages) if not message.read
            ]
            if not unread_indexes:
                await self._notify_idle()
                await self._wait_for_wake()
                continue
            for index in unread_indexes:
                message = messages[index]
                if message.type is MessageType.SHUTDOWN_REQUEST:
                    await self._box.write(
                        self._lead_agent_id,
                        new_message(
                            self._member_name,
                            "收工，再见",
                            message_type=MessageType.SHUTDOWN_RESPONSE,
                            request_id=message.request_id,
                            approve=True,
                        ),
                    )
                    return 0
                if message.type is MessageType.PLAN_APPROVAL_RESPONSE:
                    if awaiting_plan and message.request_id == awaiting_plan:
                        if message.approve is True:
                            self._mode = Mode.DEFAULT
                            awaiting_plan = ""
                            await self._run_turn(message.text or "按计划执行")
                        else:
                            awaiting_plan = ""
                            await self._run_turn(
                                "计划被驳回，请按反馈调整后重新提交：\n"
                                + (message.text or "")
                            )
                    continue
                if message.type is MessageType.PLAN_APPROVAL_REQUEST:
                    continue
                if message.type is MessageType.TEXT:
                    await self._run_turn(message.text)
                    if self._plan_mode_required:
                        awaiting_plan = await self._submit_plan_request()
            await self._box.mark_read(self._agent_id, unread_indexes)
        return 0

    async def _run_turn(self, text: str) -> None:
        self.turns += 1
        result = await self._agent.run_to_completion(
            self._conversation,
            text,
            self._mode,
            asyncio.Event(),
        )
        self._last_result = result
        await self._notify_idle()

    async def _submit_plan_request(self) -> str:
        request_id = uuid.uuid4().hex[:12]
        plan_text = (
            getattr(self._last_result, "final_text", "")
            or "（未生成计划文本）"
        )
        await self._box.write(
            self._lead_agent_id,
            new_message(
                self._member_name,
                plan_text,
                message_type=MessageType.PLAN_APPROVAL_REQUEST,
                request_id=request_id,
            ),
        )
        return request_id

    async def _notify_idle(self) -> None:
        if self._team_manager is not None:
            try:
                await self._team_manager.set_member_active(
                    self._team_name,
                    self._member_name,
                    False,
                )
            except Exception:
                pass
        if self._lead_agent_id:
            await self._box.write(
                self._lead_agent_id,
                new_message(
                    self._member_name,
                    f"[idle] {self._member_name} (reason: available)",
                ),
            )

    async def _wait_for_wake(self) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=2.0)
        except TimeoutError:
            pass
        finally:
            self._wake.clear()


def _chdir_once(worktree: str | Path) -> None:
    """独立 Pane 进程启动时唯一一次 chdir。"""

    target = str(Path(worktree).resolve())
    import os

    os.chdir(target)
    if str(Path.cwd().resolve()) != target:
        raise RuntimeError(f"chdir 校验失败: {Path.cwd()} != {target}")


async def run_team_member(
    args: Any,
    *,
    version: str = "dev",
    loop_factory: Callable[..., TeamMemberLoop] | None = None,
) -> int:
    """构造队员组件并进入自治循环。"""

    team_name = getattr(args, "team", "")
    member_name = getattr(args, "member", "")
    agent_id = getattr(args, "agent_id", "")
    session_dir = getattr(args, "session_dir", "")
    worktree = getattr(args, "worktree", "")
    for label, value in (
        ("--team", team_name),
        ("--member", member_name),
        ("--agent-id", agent_id),
        ("--session-dir", session_dir),
        ("--worktree", worktree),
    ):
        if not value:
            print(f"缺少必要参数: {label}", file=sys.stderr)
            return 2
    _chdir_once(worktree)

    if loop_factory is not None:
        loop = loop_factory(
            member_name=member_name,
            agent_id=agent_id,
            team_name=team_name,
            lead_agent_id="lead",
            box=object(),  # type: ignore[arg-type]
            agent=object(),  # type: ignore[arg-type]
            conversation=object(),  # type: ignore[arg-type]
            team_manager=None,
            plan_mode_required=bool(getattr(args, "plan_mode", False)),
        )
        return await loop.run()

    repo = Path(worktree).resolve().parent.parent
    config = load(str(repo / ".env"))
    config_provider = (
        next(
            (
                item
                for item in config.providers
                if getattr(args, "model", "") in {"", item.name}
            ),
            config.providers[0],
        )
        if config.providers
        else None
    )
    if config_provider is None:
        print("缺少可用的 provider 配置", file=sys.stderr)
        return 2
    provider = new_provider(config_provider)
    registry = new_default_registry()
    engine, _ = new_engine(str(repo))
    identity = AgentIdentity(
        agent_id=agent_id,
        parent_id="lead",
        trace_id=uuid.uuid4().hex[:12],
        agent_type=getattr(args, "agent_type", "") or "general-purpose",
        name=member_name,
        source="teammate",
        team_name=team_name,
    )
    runtime = SessionRuntime(
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=open_session_context(str(repo), Path(session_dir).name),
    )
    conversation = Conversation.from_messages(load_session(session_dir))
    scope = PermissionScope.subagent_instance(agent_id)
    ledger = PermissionLedger()
    plan_mode = bool(getattr(args, "plan_mode", False))
    child_engine = (
        engine.child(scope, ledger, Mode.PLAN if plan_mode else Mode.DONT_ASK)
        if engine is not None
        else None
    )
    agent = Agent(
        provider,
        registry,
        version,
        child_engine,
        runtime=runtime,
        identity=identity,
        permission_scope=scope,
        permission_ledger=ledger,
        max_turns=30,
    )
    from ..worktrees import WorktreeManager

    wt_mgr = await WorktreeManager.open(repo)
    from ..subagents.manager import TaskManager

    team_manager = TeamManager(
        Path.home(),
        wt_mgr=wt_mgr,
        task_mgr=TaskManager(),
    )
    team = team_manager.get(team_name)
    if team is None:
        print(f"未知 Team: {team_name}", file=sys.stderr)
        return 2
    box = Box(team.config_dir)
    loop = TeamMemberLoop(
        member_name=member_name,
        agent_id=agent_id,
        team_name=team_name,
        lead_agent_id=team.lead_agent_id,
        box=box,
        agent=agent,
        conversation=conversation,
        team_manager=team_manager,
        plan_mode_required=plan_mode,
        mailbox_dir=team.config_dir / "mailbox",
    )
    return await loop.run()
