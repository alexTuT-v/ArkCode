"""进程级运行状态与组合根。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..mcp import Manager as McpManager
from ..mcp import McpStatus
from ..memory import Manager as MemoryManager
from ..permissions import Engine
from ..skills import SkillLoader
from ..tools import Registry
from .lifecycle import close_background, close_mcp, close_memory, close_session
from .session import SessionService


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

    async def shutdown(self) -> None:
        """按 Session → Memory → 后台任务 → MCP 的顺序关闭资源。"""

        await close_session(self.session)
        await close_memory(self.memory)
        await close_background(self.cleanup_task)
        await close_mcp(self.mcp)
