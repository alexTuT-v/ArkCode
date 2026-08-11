"""/sandbox 命令测试。"""

import pytest

from Arkcode.commands import CommandKind, CommandRegistry, register_builtins
from Arkcode.commands.dispatcher import dispatch

from .fakes import make_context


def builtins() -> CommandRegistry:
    registry = CommandRegistry()
    register_builtins(registry)
    return registry


def test_builtins_now_include_sandbox() -> None:
    registry = CommandRegistry()
    register_builtins(registry)

    command = registry.lookup("sandbox")

    assert command is not None
    assert command.kind is CommandKind.LOCAL


@pytest.mark.asyncio
async def test_sandbox_status_renders_state() -> None:
    context, ui, session, _, _ = make_context()
    session.sandbox_status_value = (True, True, "SeatbeltSandbox", True)

    await dispatch(builtins(), "sandbox", context)

    assert "已启用" in ui.lines[0]
    assert "SeatbeltSandbox" in ui.lines[0]


@pytest.mark.asyncio
async def test_sandbox_enable_returns_error_message() -> None:
    context, ui, session, _, _ = make_context(args="1")
    session.sandbox_error = "错误: 当前系统不支持沙箱（仅支持 macOS / Linux）"

    await dispatch(builtins(), "sandbox", context)

    assert session.sandbox_enables == [True]
    assert "错误: 当前系统不支持沙箱" in ui.lines[0]


@pytest.mark.asyncio
async def test_sandbox_off_disables() -> None:
    context, ui, session, _, _ = make_context(args="off")

    await dispatch(builtins(), "sandbox", context)

    assert session.sandbox_disables == 1
    assert "沙箱已关闭" in ui.lines[0]
