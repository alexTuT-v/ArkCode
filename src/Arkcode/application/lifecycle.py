"""进程级生命周期：按固定顺序关闭会话、后台任务与 MCP。"""

from __future__ import annotations

import asyncio

from ..mcp import Manager as McpManager
from ..memory import Manager as MemoryManager
from .session import SessionService


async def close_session(session: SessionService) -> None:
    await session.shutdown()


async def close_background(cleanup_task: asyncio.Task[None] | None) -> None:
    if cleanup_task is not None:
        await cleanup_task


async def close_memory(memory: MemoryManager) -> None:
    await memory.shutdown()


async def close_mcp(mcp: McpManager) -> None:
    await mcp.close()
