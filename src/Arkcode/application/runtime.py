"""进程级运行状态与组合根。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import Config
from ..mcp import Manager as McpManager
from ..mcp import McpStatus
from ..memory import Manager as MemoryManager
from ..permissions import Engine
from ..skills import SkillLoader
from ..tools import Registry
from .lifecycle import close_background, close_mcp, close_memory, close_session
from .session import SessionService

if TYPE_CHECKING:
    from ..subagents.approvals import ApprovalBroker
    from ..subagents.catalog import Catalog
    from ..subagents.launcher import SubAgentLauncher
    from ..subagents.manager import TaskManager
    from ..worktrees import WorktreeManager


@dataclass
class ApplicationRuntime:
    workspace: Path
    version: str
    config: Config
    tools: Registry
    permissions: Engine
    mcp: McpManager
    mcp_status: McpStatus
    memory: MemoryManager
    skills: SkillLoader
    session: SessionService
    cleanup_task: asyncio.Task[None] | None = None
    catalog: Catalog | None = None
    task_manager: TaskManager | None = None
    approval_broker: ApprovalBroker | None = None
    launcher: SubAgentLauncher | None = None
    worktree_manager: WorktreeManager | None = None
    sweep_task: asyncio.Task[None] | None = None

    async def shutdown(self) -> None:
        """按 Session → Memory → SubAgent 任务 → 后台任务 → MCP 的顺序关闭。"""

        await close_session(self.session)
        await close_memory(self.memory)
        if self.task_manager is not None:
            await self.task_manager.shutdown()
        if self.approval_broker is not None:
            self.approval_broker.cancel_all()
        await close_background(self.cleanup_task)
        await close_background(self.sweep_task)
        await close_mcp(self.mcp)
