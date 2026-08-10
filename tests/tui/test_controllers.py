"""TUI 控制器单元测试。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from Arkcode.agents import ApprovalRequest
from Arkcode.config import ProviderConfig
from Arkcode.llm import Message
from Arkcode.permissions import Outcome
from Arkcode.sessions import SessionJournal, SessionMeta, SessionMetaStore
from Arkcode.tui.controllers.approvals import ApprovalController
from Arkcode.tui.controllers.chat import ChatController
from Arkcode.tui.controllers.providers import ProviderController
from Arkcode.tui.controllers.sessions import SessionController
from Arkcode.tui.controllers.skills import SkillsController
from Arkcode.tui.state import SessionState

from .fakes import FakeApp, FakeSession


class FakeCommands:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    async def dispatch(self, text: str) -> bool:
        self.dispatched.append(text)
        return text.startswith("/")


class FakeSessionWithSubmit(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.submitted_messages: list[str] = []

    async def submit_message(self, text: str) -> object:
        self.submitted_messages.append(text)
        if False:
            yield None


@pytest.mark.asyncio
async def test_chat_sends_slash_to_dispatcher_and_plain_to_session() -> None:
    commands = FakeCommands()
    app = FakeApp()
    session = FakeSessionWithSubmit()
    chat = ChatController(app, session, commands)  # type: ignore[arg-type]

    await chat.submit("/status")
    await chat.submit("hello")
    if app._stream_task is not None:
        await app._stream_task

    assert commands.dispatched == ["/status", "hello"]
    assert session.submitted_messages == ["hello"]
    assert app.input.text == ""


def test_provider_controller_activates_exactly_the_selected_config() -> None:
    session = FakeSession()
    app = FakeApp()
    provider = ProviderController(app, session)  # type: ignore[arg-type]
    config = ProviderConfig(
        name="Claude", protocol="anthropic", api_key="secret", model="claude-test"
    )

    provider.activate(config)

    assert session.activated == [config]
    assert app.skills.registered == 0


@pytest.mark.asyncio
async def test_approval_controller_resolves_each_outcome_once() -> None:
    app = FakeApp()
    respond = asyncio.get_running_loop().create_future()
    app.pending = ApprovalRequest("bash", "git status", "需要确认", respond)
    controller = ApprovalController(app)

    controller.update("1")
    assert respond.result() is Outcome.ALLOW_ONCE
    assert app.pending is None


@pytest.mark.asyncio
async def test_approval_keyboard_mapping_and_navigation() -> None:
    outcomes = {
        "2": Outcome.ALLOW_FOREVER,
        "3": Outcome.DENY_ONCE,
        "y": Outcome.ALLOW_ONCE,
        "n": Outcome.DENY_ONCE,
        "enter": Outcome.ALLOW_FOREVER,
    }
    for key, expected in outcomes.items():
        app = FakeApp()
        respond = asyncio.get_running_loop().create_future()
        app.pending = ApprovalRequest("bash", "git status", "需要确认", respond)
        controller = ApprovalController(app)

        controller.update("down")
        assert app.approve_cursor == 1
        controller.update(key)

        assert respond.done()
        assert respond.result() is expected


def test_skills_controller_reloads_through_session_without_agent_internals() -> None:
    session = FakeSession()

    class RecordingAgent:
        def __init__(self) -> None:
            self.catalogs: list[str] = []

        def set_skill_catalog(self, catalog: str) -> None:
            self.catalogs.append(catalog)

    agent = RecordingAgent()
    session.agent = agent
    app = FakeApp()
    controller = SkillsController(app, session)  # type: ignore[arg-type]

    controller.reload_skills()

    assert len(agent.catalogs) == 1
    assert app.cmd_registry.lookup("help") is not None
    assert app.cmd_registry.lookup("skill") is not None


def _write_session(root: Path, session_id: str) -> Path:
    target = root / ".Arkcode" / "sessions" / session_id
    journal = SessionJournal(target)
    journal.append_message(Message(role="user", content="恢复这段对话"))
    journal.close()
    SessionMetaStore(target).save(
        replace(
            SessionMeta.new(session_id),
            title="恢复这段对话",
            model="old-model",
        )
    )
    return target


def test_session_controller_begins_and_cancels_resume_mode(
    tmp_path: Path,
) -> None:
    _write_session(tmp_path, "20260807-120000-aaaa")
    _write_session(tmp_path, "20260808-120000-bbbb")
    session = FakeSession()
    app = FakeApp()
    app.sessions_dir = str(tmp_path / ".Arkcode" / "sessions")
    controller = SessionController(app, session)  # type: ignore[arg-type]

    controller.begin_resume()
    assert app.state is SessionState.RESUMING
    assert app.resume_list.display is True

    controller.cancel_resume()
    assert app.state is SessionState.IDLE
    assert app.input.disabled is False


@pytest.mark.asyncio
async def test_session_controller_resume_delegates_selected_info(
    tmp_path: Path,
) -> None:
    target = _write_session(tmp_path, "20260808-120000-bbbb")
    session = FakeSession()
    app = FakeApp()
    app.sessions_dir = str(tmp_path / ".Arkcode" / "sessions")
    controller = SessionController(app, session)  # type: ignore[arg-type]

    from Arkcode.sessions import list_sessions

    info = next(
        item for item in list_sessions(app.sessions_dir) if item.id == target.name
    )
    await controller.resume(info)

    assert session.resumed == [info]
    assert app.state is SessionState.IDLE
