"""/memory 子命令测试。"""

import pytest

from Arkcode.commands import CommandRegistry, register_builtins
from Arkcode.commands.dispatcher import dispatch

from .fakes import make_context


def builtins() -> CommandRegistry:
    registry = CommandRegistry()
    register_builtins(registry)
    return registry


@pytest.mark.asyncio
async def test_memory_clear_delegates() -> None:
    context, ui, session, _, _ = make_context(args="clear")

    await dispatch(builtins(), "memory", context)

    assert session.memory_cleared == 1
    assert "所有记忆已清空" in ui.lines[0]


@pytest.mark.asyncio
async def test_memory_edit_shows_directories() -> None:
    context, ui, session, _, status = make_context(args="edit")
    status.memory_dirs_value = ("/work/.Arkcode/memory", "/home/.Arkcode/memory")

    await dispatch(builtins(), "memory", context)

    assert "/work/.Arkcode/memory" in ui.lines[0]
    assert "/home/.Arkcode/memory" in ui.lines[0]
