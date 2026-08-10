"""MCP 调用懒重连测试。"""

import pytest

from Arkcode.mcp.manager import Manager


class FlakyCaller:
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(self, name: str, arguments: dict | None = None):
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("broken")
        return object()


@pytest.mark.asyncio
async def test_call_server_tool_retries_once_after_reconnect(monkeypatch) -> None:
    manager = Manager()
    caller = FlakyCaller()

    def fake_get_client(name: str):
        return caller

    async def fake_reconnect(name: str) -> None:
        return None

    monkeypatch.setattr(manager, "get_client", fake_get_client)
    monkeypatch.setattr(manager, "_reconnect_server", fake_reconnect)

    result = await manager.call_server_tool("demo", "echo", {})

    assert caller.calls == 2
    assert result is not None


@pytest.mark.asyncio
async def test_call_server_tool_raises_when_unavailable(monkeypatch) -> None:
    manager = Manager()

    def fake_get_client(name: str):
        return None

    async def fake_reconnect(name: str) -> None:
        manager._failures[name] = "still down"

    monkeypatch.setattr(manager, "get_client", fake_get_client)
    monkeypatch.setattr(manager, "_reconnect_server", fake_reconnect)

    with pytest.raises(RuntimeError, match="still down"):
        await manager.call_server_tool("demo", "echo", {})
