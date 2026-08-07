import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
import mcp.types as mtypes
import pytest
from mcp.server.mcpserver import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from Arkcode.mcp import Config, ServerConfig
from Arkcode.mcp import manager as manager_module
from Arkcode.mcp.manager import Manager, new_manager
from Arkcode.mcp.tool import McpTool


class NoopCaller:
    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> mtypes.CallToolResult:
        return mtypes.CallToolResult(content=[])


def _tool(name: str) -> McpTool:
    return McpTool(
        full_name=name,
        remote_name="remote",
        tool_description="test",
        input_schema={"type": "object"},
        _read_only=False,
        caller=NoopCaller(),
    )


@pytest.mark.asyncio
async def test_empty_manager_has_no_tools_and_closes_immediately() -> None:
    manager = await new_manager(Config(), "test")

    assert manager.tools() == []
    await manager.close()


@pytest.mark.asyncio
async def test_connection_failure_isolated_and_tools_are_stably_sorted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def connect_stub(
        manager: Manager,
        name: str,
        server: ServerConfig,
        version: str,
        ready: asyncio.Future[Exception | None],
    ) -> None:
        if name == "broken":
            raise RuntimeError("handshake failed")
        await asyncio.sleep(0 if name == "alpha" else 0.01)
        async with manager._lock:
            manager._tools.append(_tool(f"mcp__{name}__echo"))
        ready.set_result(None)
        await manager._stop.wait()

    monkeypatch.setattr(manager_module, "_do_connect", connect_stub)
    config = Config(
        {
            "zeta": ServerConfig(type="stdio", command="zeta"),
            "broken": ServerConfig(type="stdio", command="broken"),
            "alpha": ServerConfig(type="stdio", command="alpha"),
        }
    )

    manager = await new_manager(config, "test")

    assert [tool.name() for tool in manager.tools()] == [
        "mcp__alpha__echo",
        "mcp__zeta__echo",
    ]
    assert "connect server broken failed: handshake failed" in capsys.readouterr().err
    await manager.close()


@pytest.mark.asyncio
async def test_status_reports_configured_connected_failed_and_registered_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def connect_stub(
        manager: Manager,
        name: str,
        server: ServerConfig,
        version: str,
        ready: asyncio.Future[Exception | None],
    ) -> None:
        if name == "broken":
            raise RuntimeError("handshake failed")
        async with manager._lock:
            manager._sessions.append(object())  # type: ignore[arg-type]
            manager._tools.extend(
                _tool(f"mcp__healthy__tool_{index}") for index in range(3)
            )
        ready.set_result(None)
        await manager._stop.wait()

    monkeypatch.setattr(manager_module, "_do_connect", connect_stub)
    config = Config(
        {
            "healthy": ServerConfig(type="stdio", command="healthy"),
            "broken": ServerConfig(type="stdio", command="broken"),
        }
    )

    manager = await new_manager(config, "test")

    status = manager.status()
    assert status.configured_servers == 2
    assert status.connected_servers == 1
    assert status.registered_tools == 3
    assert status.failed_servers == 1
    await manager.close()


@pytest.mark.asyncio
async def test_status_counts_connected_server_that_registers_no_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def connect_stub(
        manager: Manager,
        name: str,
        server: ServerConfig,
        version: str,
        ready: asyncio.Future[Exception | None],
    ) -> None:
        async with manager._lock:
            manager._sessions.append(object())  # type: ignore[arg-type]
        ready.set_result(None)
        await manager._stop.wait()

    monkeypatch.setattr(manager_module, "_do_connect", connect_stub)
    config = Config({"empty": ServerConfig(type="stdio", command="empty")})

    manager = await new_manager(config, "test")

    status = manager.status()
    assert status.configured_servers == 1
    assert status.connected_servers == 1
    assert status.registered_tools == 0
    assert status.failed_servers == 0
    await manager.close()


@pytest.mark.asyncio
async def test_stuck_connection_times_out_without_blocking_startup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def connect_stub(
        manager: Manager,
        name: str,
        server: ServerConfig,
        version: str,
        ready: asyncio.Future[Exception | None],
    ) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(manager_module, "_do_connect", connect_stub)
    monkeypatch.setattr(manager_module, "connect_timeout", 0.01)
    config = Config({"stuck": ServerConfig(type="stdio", command="stuck")})

    manager = await asyncio.wait_for(new_manager(config, "test"), timeout=0.2)

    assert manager.tools() == []
    assert "connect server stuck timeout" in capsys.readouterr().err
    await manager.close()


@pytest.mark.asyncio
async def test_close_timeout_returns_and_warns(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manager = Manager()

    async def block_close() -> None:
        await asyncio.Event().wait()

    blocked = asyncio.create_task(block_close())
    manager._tasks.append(blocked)
    monkeypatch.setattr(manager_module, "close_timeout", 0.01)

    await asyncio.wait_for(manager.close(), timeout=0.2)

    assert "close timeout" in capsys.readouterr().err
    await asyncio.sleep(0)
    assert blocked.cancelled()


@pytest.mark.asyncio
async def test_stdio_transport_receives_merged_environment_and_lists_tools(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_stdio(params: Any):
        observed["params"] = params
        yield object(), object()

    class FakeSession:
        def __init__(
            self, read: object, write: object, client_info: mtypes.Implementation
        ) -> None:
            observed["client_info"] = client_info

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *args: object) -> None:
            observed["closed"] = True

        async def initialize(self) -> None:
            observed["initialized"] = True

        async def list_tools(self) -> Any:
            return type(
                "Listed",
                (),
                {
                    "tools": [
                        mtypes.Tool(
                            name="echo",
                            description="first",
                            inputSchema={"type": "object"},
                        ),
                        mtypes.Tool(
                            name="echo",
                            description="second",
                            inputSchema={"type": "object"},
                        ),
                    ]
                },
            )()

        async def call_tool(
            self, name: str, arguments: dict[str, Any] | None = None
        ) -> mtypes.CallToolResult:
            return mtypes.CallToolResult(content=[])

    monkeypatch.setenv("HOST_ONLY", "host")
    monkeypatch.setenv("OVERRIDE", "host-value")
    monkeypatch.setattr(manager_module, "stdio_client", fake_stdio)
    monkeypatch.setattr(manager_module, "ClientSession", FakeSession)
    config = Config(
        {
            "demo": ServerConfig(
                type="stdio",
                command="python",
                args=["server.py"],
                env={"OVERRIDE": "server-value"},
            )
        }
    )

    manager = await new_manager(config, "1.2.3")

    params = observed["params"]
    assert params.command == "python"
    assert params.args == ["server.py"]
    assert params.env["HOST_ONLY"] == "host"
    assert params.env["OVERRIDE"] == "server-value"
    assert observed["initialized"] is True
    assert [tool.name() for tool in manager.tools()] == ["mcp__demo__echo"]
    assert manager.tools()[0].description() == "second"
    assert "duplicate tool mcp__demo__echo" in capsys.readouterr().err
    await manager.close()
    assert observed["closed"] is True


@pytest.mark.asyncio
async def test_http_transport_receives_configured_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class FakeHttpClient:
        def __init__(self, headers: dict[str, str] | None) -> None:
            observed["headers"] = headers

        async def __aenter__(self) -> "FakeHttpClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

    def fake_http_client(
        headers: dict[str, str] | None = None,
    ) -> FakeHttpClient:
        return FakeHttpClient(headers)

    @asynccontextmanager
    async def fake_http(url: str, *, http_client: FakeHttpClient):
        observed.update(url=url, http_client=http_client)
        yield object(), object(), None

    class FakeSession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def initialize(self) -> None:
            pass

        async def list_tools(self) -> Any:
            return type("Listed", (), {"tools": []})()

    monkeypatch.setattr(manager_module, "streamable_http_client", fake_http)
    monkeypatch.setattr(manager_module, "create_mcp_http_client", fake_http_client)
    monkeypatch.setattr(manager_module, "ClientSession", FakeSession)
    config = Config(
        {
            "remote": ServerConfig(
                type="http",
                url="https://example.test/mcp",
                headers={"Authorization": "Bearer test-value"},
            )
        }
    )

    manager = await new_manager(config, "test")

    assert observed["url"] == "https://example.test/mcp"
    assert observed["headers"] == {"Authorization": "Bearer test-value"}
    assert isinstance(observed["http_client"], FakeHttpClient)
    await manager.close()


@pytest.mark.asyncio
async def test_real_stdio_server_handshake_call_env_and_shutdown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    server_script = Path(__file__).parent / "fixtures" / "mcp_stdio_server.py"
    config = Config(
        {
            "real": ServerConfig(
                type="stdio",
                command=sys.executable,
                args=[str(server_script)],
                env={"ARKCODE_MCP_TEST_VALUE": "injected"},
            )
        }
    )
    manager = await new_manager(config, "test")

    tools = manager.tools()
    assert [tool.name() for tool in tools] == ["mcp__real__echo"]
    assert tools[0].read_only is True
    result = await tools[0].execute('{"value": "hello"}')
    pid_text, injected, echoed = result.content.split("|")
    child_pid = int(pid_text)
    assert result.is_error is False
    assert (injected, echoed) == ("injected", "hello")

    await manager.close()
    assert "close failed" not in capsys.readouterr().err

    for _ in range(100):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail(f"stdio MCP 子进程仍存活: {child_pid}")


@pytest.mark.asyncio
async def test_real_http_server_handshake_headers_and_call() -> None:
    seen_authorization: list[str | None] = []

    class CaptureAuthorization(BaseHTTPMiddleware):
        async def dispatch(
            self, request: Request, call_next: RequestResponseEndpoint
        ) -> Response:
            seen_authorization.append(request.headers.get("authorization"))
            return await call_next(request)

    remote = MCPServer("arkcode-http-test", version="1.0")

    @remote.tool()
    def echo(value: str) -> str:
        return value

    app = remote.streamable_http_app(stateless_http=True)
    app.add_middleware(CaptureAuthorization)

    def in_memory_http_client(
        headers: dict[str, str] | None = None,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            headers=headers,
            transport=httpx2.ASGITransport(app=app),
            base_url="http://127.0.0.1:8123",
        )

    original_factory = manager_module.create_mcp_http_client
    manager_module.create_mcp_http_client = in_memory_http_client
    try:
        async with app.router.lifespan_context(app):
            manager = await new_manager(
                Config(
                    {
                        "http": ServerConfig(
                            type="http",
                            url="http://127.0.0.1:8123/mcp",
                            headers={"Authorization": "Bearer integration-test"},
                        )
                    }
                ),
                "test",
            )
            tools = manager.tools()
            assert [tool.name() for tool in tools] == ["mcp__http__echo"]
            result = await tools[0].execute('{"value": "hello-http"}')
            assert result.content == "hello-http"
            assert result.is_error is False
            assert seen_authorization
            assert set(seen_authorization) == {"Bearer integration-test"}
            await manager.close()
    finally:
        manager_module.create_mcp_http_client = original_factory
