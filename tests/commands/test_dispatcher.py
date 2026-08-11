"""dispatch 的统一策略测试。"""

from __future__ import annotations

import pytest

from Arkcode.commands import Command, CommandContext, CommandKind, CommandRegistry
from Arkcode.commands.dispatcher import BUSY_MESSAGE, dispatch

from .fakes import make_context


@pytest.mark.asyncio
async def test_dispatch_passes_parsed_arguments_to_handler() -> None:
    received: list[str] = []

    async def handler(context: CommandContext) -> None:
        received.append(context.args)

    registry = CommandRegistry()
    registry.register(Command("sample", "sample", CommandKind.LOCAL, handler))
    context, _, _, _, _ = make_context(args="value")

    handled = await dispatch(registry, "sample", context)

    assert handled is True
    assert received == ["value"]


@pytest.mark.asyncio
async def test_dispatch_returns_false_for_unknown_command() -> None:
    registry = CommandRegistry()
    context, ui, _, _, _ = make_context()

    handled = await dispatch(registry, "missing", context)

    assert handled is False
    assert ui.lines == []
    assert ui.errors == []


@pytest.mark.asyncio
async def test_dispatch_rejects_ui_and_prompt_commands_while_busy() -> None:
    registry = CommandRegistry()
    registry.register(Command("clear", "clear", CommandKind.UI, _noop))
    registry.register(Command("do", "do", CommandKind.PROMPT, _noop))
    context, ui, session, _, _ = make_context()
    session.busy = True

    assert await dispatch(registry, "clear", context) is True
    assert await dispatch(registry, "do", context) is True
    assert ui.errors == [BUSY_MESSAGE, BUSY_MESSAGE]


@pytest.mark.asyncio
async def test_dispatch_runs_local_commands_while_busy() -> None:
    registry = CommandRegistry()
    ran: list[str] = []

    async def handler(context: CommandContext) -> None:
        ran.append(context.args)

    registry.register(Command("status", "status", CommandKind.LOCAL, handler))
    context, _, session, _, _ = make_context(args="x")
    session.busy = True

    assert await dispatch(registry, "status", context) is True
    assert ran == ["x"]


@pytest.mark.asyncio
async def test_dispatch_converts_handler_errors_to_ui_error() -> None:
    registry = CommandRegistry()

    async def broken(context: CommandContext) -> None:
        raise RuntimeError("boom")

    registry.register(Command("broken", "broken", CommandKind.LOCAL, broken))
    context, ui, _, _, _ = make_context()

    assert await dispatch(registry, "broken", context) is True
    assert ui.errors == ["boom"]


async def _noop(context: CommandContext) -> None:
    return None
