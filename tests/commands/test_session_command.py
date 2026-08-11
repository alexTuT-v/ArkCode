"""/session 子命令测试。"""

import pytest

from Arkcode.commands import CommandRegistry, register_builtins
from Arkcode.commands.dispatcher import dispatch

from .fakes import FakeStatus, make_context


def builtins() -> CommandRegistry:
    registry = CommandRegistry()
    register_builtins(registry)
    return registry


@pytest.mark.asyncio
async def test_session_list_renders_sessions() -> None:
    context, ui, session, _, status = make_context(args="list")
    status.sessions = [
        FakeStatus.SessionRow("20260808-120000-abcd", "alpha topic", 1234),
        FakeStatus.SessionRow("20260807-120000-aaaa", "beta topic", 56),
    ]

    await dispatch(builtins(), "session", context)

    assert "20260808-120000-abcd" in ui.lines[0]
    assert "alpha topic" in ui.lines[0]


@pytest.mark.asyncio
async def test_session_resume_delegates_by_id() -> None:
    context, ui, session, _, status = make_context(args="resume 20260808-120000-abcd")
    status.sessions = [
        FakeStatus.SessionRow("20260808-120000-abcd", "alpha", 10),
    ]

    await dispatch(builtins(), "session", context)

    assert session.resumed_by_id == ["20260808-120000-abcd"]


@pytest.mark.asyncio
async def test_session_delete_refuses_current_session() -> None:
    context, ui, session, _, status = make_context(args="delete 20260808-120000-abcd")
    status.session_id_value = "20260808-120000-abcd"

    await dispatch(builtins(), "session", context)

    assert session.deleted == []
    assert "不能删除当前活跃的会话" in ui.lines[0]


@pytest.mark.asyncio
async def test_session_unknown_subcommand_shows_usage() -> None:
    context, ui, session, _, _ = make_context(args="wat")

    await dispatch(builtins(), "session", context)

    assert "用法: /session" in ui.lines[0]
