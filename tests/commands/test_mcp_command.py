"""/mcp 命令测试。"""

import pytest

from Arkcode.commands import CommandKind, CommandRegistry, register_builtins
from Arkcode.commands.dispatcher import dispatch

from .fakes import FakeStatus, make_context


def builtins() -> CommandRegistry:
    registry = CommandRegistry()
    register_builtins(registry)
    return registry


def test_builtins_now_include_mcp() -> None:
    registry = CommandRegistry()
    register_builtins(registry)

    names = [item.name for item in registry.visible()]

    assert "mcp" in names
    assert names[-2] == "status"
    assert names[-1] == "worktree"
    assert registry.lookup("mcp").kind is CommandKind.LOCAL


@pytest.mark.asyncio
async def test_mcp_renders_server_status() -> None:
    context, ui, session, _, status = make_context()
    status.servers = [
        FakeStatus.ServerRow("demo", 1, True, None),
        FakeStatus.ServerRow("broken", 0, False, "connect refused"),
    ]

    await dispatch(builtins(), "mcp", context)

    assert "1/2 已连接" in ui.lines[0]
    assert "demo" in ui.lines[0]
    assert "broken" in ui.lines[0]
    assert "connect refused" in ui.lines[0]


@pytest.mark.asyncio
async def test_mcp_reports_unconfigured() -> None:
    context, ui, session, _, status = make_context()

    await dispatch(builtins(), "mcp", context)

    assert "未配置 MCP" in ui.lines[0]
