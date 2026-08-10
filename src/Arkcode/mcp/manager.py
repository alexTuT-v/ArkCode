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
from .tool_adapter import CallerSession, McpTool, adapt_tool

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
    mcp_instructions: str = ""


@dataclass(frozen=True)
class McpStatus:
    """MCP 启动完成后的汇总快照。"""

    configured_servers: int
    connected_servers: int
    registered_tools: int

    @property
    def failed_servers(self) -> int:
        return self.configured_servers - self.connected_servers


@dataclass(frozen=True)
class McpServerStatus:
    """单个 MCP server 的运行时状态。"""

    name: str
    tool_count: int
    connected: bool
    error: str | None = None


class Manager:
    """持有启动成功的会话和它们暴露的工具。"""

    def __init__(self, configured_servers: int = 0) -> None:
        self._lock = asyncio.Lock()
        self._configured_servers = configured_servers
        self._configs: dict[str, ServerConfig] = {}
        self._version = ""
        self._sessions: list[_Session] = []
        self._tools: list[McpTool] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._failures: dict[str, str] = {}
        self._stop = asyncio.Event()
        self._closed = False

    def get_client(self, name: str) -> Any | None:
        """返回已连接会话；未连接时返回 None（调用方可触发重连）。"""

        for session in self._sessions:
            if session.name == name:
                return session.session
        return None

    async def _reconnect_server(self, name: str) -> None:
        """关闭并重连单个 server；失败记录到 _failures。"""

        for task in self._tasks:
            if task.get_name() == f"mcp:{name}" and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._sessions = [item for item in self._sessions if item.name != name]
        self._tools = [
            item
            for item in self._tools
            if not item.full_name.startswith(f"mcp__{name}__")
        ]
        server = self._configs.get(name)
        if server is None:
            self._failures[name] = "server config not found"
            return
        ready: asyncio.Future[Exception | None] = (
            asyncio.get_running_loop().create_future()
        )
        task = asyncio.create_task(
            _connect_one(self, name, server, self._version, ready),
            name=f"mcp:{name}",
        )
        self._tasks.append(task)
        try:
            error = await asyncio.wait_for(
                asyncio.shield(ready),
                timeout=connect_timeout,
            )
        except TimeoutError:
            error = RuntimeError("reconnect timeout")
        if error is not None:
            self._failures[name] = str(error)

    async def call_server_tool(
        self,
        name: str,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> Any:
        """调用远端工具；连接断开时重连一次再重试。"""

        caller = self.get_client(name)
        if caller is None:
            await self._reconnect_server(name)
            caller = self.get_client(name)
            if caller is None:
                raise RuntimeError(
                    self._failures.get(name, f"server {name} unavailable")
                )
        try:
            return await caller.call_tool(tool_name, arguments)
        except Exception as error:
            await self._reconnect_server(name)
            caller = self.get_client(name)
            if caller is None:
                raise error
            return await caller.call_tool(tool_name, arguments)

    def tools(self) -> list[McpTool]:
        return list(self._tools)

    def status(self) -> McpStatus:
        return McpStatus(
            configured_servers=self._configured_servers,
            connected_servers=len(self._sessions),
            registered_tools=len(self._tools),
        )

    def server_summary(self) -> list[McpServerStatus]:
        connected = {session.name for session in self._sessions}
        counts: dict[str, int] = {}
        for tool in self._tools:
            parts = tool.full_name.split("__")
            if len(parts) >= 3:
                server = parts[1]
                counts[server] = counts.get(server, 0) + 1
        names = sorted(set(connected) | set(self._failures))
        return [
            McpServerStatus(
                name=name,
                tool_count=counts.get(name, 0),
                connected=name in connected,
                error=self._failures.get(name),
            )
            for name in names
        ]

    def instructions_text(self) -> str:
        """按 server 名生成 MCP 指令段落；无 instructions 时列工具名。"""

        if not self._sessions:
            return ""
        parts: list[str] = []
        for session in sorted(self._sessions, key=lambda item: item.name):
            section = f"## {session.name}\n"
            if session.mcp_instructions:
                section += session.mcp_instructions
            else:
                tool_names = [
                    tool.full_name
                    for tool in self._tools
                    if tool.full_name.startswith(f"mcp__{session.name}__")
                ]
                if tool_names:
                    section += "Available tools: " + ", ".join(tool_names)
            parts.append(section)
        return "# MCP Server Instructions\n\n" + "\n\n".join(parts)

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
    manager._configs = dict(cfg.servers)
    manager._version = version
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
        manager._failures[name] = str(error)
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
        init_result = await session.initialize()
        server_instructions = getattr(init_result, "instructions", "") or ""
        listed = await session.list_tools()
        caller = cast(CallerSession, session)
        adapted_by_name: dict[str, McpTool] = {}
        for remote in listed.tools:
            tool = adapt_tool(name, remote, caller, manager=manager)
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
            manager._sessions.append(
                _Session(
                    name=name, session=session, mcp_instructions=server_instructions
                )
            )
            manager._tools.extend(adapted)
            manager._failures.pop(name, None)
        ready.set_result(None)
        await manager._stop.wait()
