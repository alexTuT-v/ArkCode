"""MCP server 的并发连接与生命周期管理。"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, cast

import mcp.types as mtypes
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import Config, ServerConfig
from .tool import CallerSession, McpTool, adapt_tool

_http_module = importlib.import_module("mcp.client.streamable_http")
streamable_http_client: Any = getattr(_http_module, "streamable_http_client", None)
if streamable_http_client is None:  # pragma: no cover - mcp 1.x 兼容分支
    streamable_http_client = getattr(_http_module, "streamablehttp_client")
create_mcp_http_client: Any = getattr(_http_module, "create_mcp_http_client", None)
_HTTP_USES_CLIENT = create_mcp_http_client is not None

connect_timeout: float = 30.0
close_timeout: float = 5.0


@dataclass
class _Session:
    name: str
    session: Any


@dataclass(frozen=True)
class McpStatus:
    """MCP 启动完成后的汇总快照。"""

    configured_servers: int
    connected_servers: int
    registered_tools: int

    @property
    def failed_servers(self) -> int:
        return self.configured_servers - self.connected_servers


class Manager:
    """持有启动成功的会话和它们暴露的工具。"""

    def __init__(self, configured_servers: int = 0) -> None:
        self._lock = asyncio.Lock()
        self._configured_servers = configured_servers
        self._sessions: list[_Session] = []
        self._tools: list[McpTool] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._stop = asyncio.Event()
        self._closed = False

    def tools(self) -> list[McpTool]:
        return list(self._tools)

    def status(self) -> McpStatus:
        return McpStatus(
            configured_servers=self._configured_servers,
            connected_servers=len(self._sessions),
            registered_tools=len(self._tools),
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if not self._tasks:
            return
        _, pending = await asyncio.wait(self._tasks, timeout=close_timeout)
        if pending:
            print(
                f"[mcp] warn: close timeout ({close_timeout:g}s), "
                "some sessions may leak",
                file=sys.stderr,
            )
            for task in pending:
                task.cancel()


async def new_manager(cfg: Config, version: str) -> Manager:
    """并发连接全部 server；单个失败不会向调用方传播。"""

    manager = Manager(configured_servers=len(cfg.servers))
    ready_items: list[tuple[str, asyncio.Future[Exception | None]]] = []
    for name, server in cfg.servers.items():
        ready: asyncio.Future[Exception | None] = (
            asyncio.get_running_loop().create_future()
        )
        task = asyncio.create_task(
            _connect_one(manager, name, server, version, ready),
            name=f"mcp:{name}",
        )
        manager._tasks.append(task)
        ready_items.append((name, ready))
    if ready_items:
        await asyncio.gather(
            *(_wait_until_ready(manager, name, ready) for name, ready in ready_items)
        )
    manager._tools.sort(key=lambda tool: tool.full_name)
    return manager


async def _connect_one(
    manager: Manager,
    name: str,
    server: ServerConfig,
    version: str,
    ready: asyncio.Future[Exception | None],
) -> None:
    try:
        await _do_connect(manager, name, server, version, ready)
        if not ready.done():
            ready.set_result(RuntimeError("connection ended before initialization"))
    except asyncio.CancelledError:
        if not ready.done():
            ready.set_result(RuntimeError("connection cancelled"))
        raise
    except Exception as exc:
        if not ready.done():
            ready.set_result(exc)


async def _wait_until_ready(
    manager: Manager,
    name: str,
    ready: asyncio.Future[Exception | None],
) -> None:
    try:
        error = await asyncio.wait_for(asyncio.shield(ready), timeout=connect_timeout)
    except TimeoutError:
        print(
            f"[mcp] warn: connect server {name} timeout after {connect_timeout:g}s",
            file=sys.stderr,
        )
        for task in manager._tasks:
            if not task.done() and task.get_name() == f"mcp:{name}":
                task.cancel()
        return
    if error is not None:
        print(f"[mcp] warn: connect server {name} failed: {error}", file=sys.stderr)


async def _do_connect(
    manager: Manager,
    name: str,
    server: ServerConfig,
    version: str,
    ready: asyncio.Future[Exception | None],
) -> None:
    # SDK 的 AnyIO cancel scope 必须在创建它的同一 task 中退出。
    async with AsyncExitStack() as local_stack:
        if server.type == "stdio":
            params = StdioServerParameters(
                command=server.command,
                args=server.args,
                env={**os.environ, **server.env},
            )
            transport_context = stdio_client(params)
        else:
            if _HTTP_USES_CLIENT:
                http_client = await local_stack.enter_async_context(
                    create_mcp_http_client(headers=server.headers or None)
                )
                transport_context = streamable_http_client(
                    server.url, http_client=http_client
                )
            else:  # pragma: no cover - mcp 1.x 兼容分支
                transport_context = streamable_http_client(
                    server.url, headers=server.headers or None
                )

        transport = await local_stack.enter_async_context(transport_context)
        read, write = transport[0], transport[1]
        session = await local_stack.enter_async_context(
            ClientSession(
                read,
                write,
                client_info=mtypes.Implementation(name="Arkcode", version=version),
            )
        )
        await session.initialize()
        listed = await session.list_tools()
        caller = cast(CallerSession, session)
        adapted_by_name: dict[str, McpTool] = {}
        for remote in listed.tools:
            tool = adapt_tool(name, remote, caller)
            if tool is None:
                continue
            if tool.full_name in adapted_by_name:
                print(
                    f"[mcp] warn: duplicate tool {tool.full_name}; keeping later one",
                    file=sys.stderr,
                )
            adapted_by_name[tool.full_name] = tool
        adapted = list(adapted_by_name.values())

        async with manager._lock:
            manager._sessions.append(_Session(name=name, session=session))
            manager._tools.extend(adapted)
        ready.set_result(None)
        await manager._stop.wait()
