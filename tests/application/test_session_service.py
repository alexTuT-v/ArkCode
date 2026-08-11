"""SessionService 生命周期与状态所有权测试。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

import Arkcode.application.session as session_module
from Arkcode.agents import NOTICE_CANCELLED
from Arkcode.application import SessionService
from Arkcode.config import Config, Features, ProviderConfig
from Arkcode.llm import Message, StreamEnd, TextDelta
from Arkcode.permissions import Mode, new_engine
from Arkcode.sessions import (
    SessionJournal,
    SessionMeta,
    SessionMetaStore,
    list_sessions,
)
from Arkcode.skills import SkillLoader
from Arkcode.tools import new_default_registry


def make_service(tmp_path: Path) -> SessionService:
    engine, error = new_engine(str(tmp_path))
    assert error is None
    skills = SkillLoader(tmp_path)
    skills.load_all()
    return SessionService(
        workspace=tmp_path,
        version="0.1.0",
        registry=new_default_registry(),
        permissions=engine,
        skills=skills,
    )


def config() -> ProviderConfig:
    return ProviderConfig(
        name="fake", protocol="openai", api_key="secret", model="main-model"
    )


@pytest.mark.asyncio
async def test_coordinator_mode_filters_agent_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, error = new_engine(str(tmp_path))
    assert error is None
    skills = SkillLoader(tmp_path)
    skills.load_all()
    registry = new_default_registry()
    from Arkcode.subagents.approvals import ApprovalBroker
    from Arkcode.subagents.catalog import Catalog
    from Arkcode.subagents.launcher import SubAgentLauncher
    from Arkcode.subagents.manager import TaskManager
    from Arkcode.subagents.tools import AgentTool, JobStopTool
    from Arkcode.teams.manager import TeamManager
    from Arkcode.teams.tools import (
        SendMessageTool,
        TeamDeleteTool,
        TeamServices,
    )

    task_manager = TaskManager()
    launcher = SubAgentLauncher(
        catalog=Catalog(project_root=tmp_path, user_root=tmp_path),
        task_manager=task_manager,
        broker=ApprovalBroker(),
        engine=engine,
        version="test",
        workspace=tmp_path,
    )
    team_manager = TeamManager(tmp_path, task_mgr=task_manager)
    services = TeamServices(
        team_manager=team_manager,
        task_manager=task_manager,
    )
    registry.register(AgentTool(launcher))
    registry.register(JobStopTool(task_manager))
    registry.register(SendMessageTool(services))
    registry.register(TeamDeleteTool(services))
    service = SessionService(
        workspace=tmp_path,
        version="test",
        registry=registry,
        permissions=engine,
        skills=skills,
        config=Config(
            providers=[],
            features=Features(coordinator_mode=True),
        ),
    )
    monkeypatch.setenv("ArkCODE_COORDINATOR_MODE", "1")
    from Arkcode.teams.coordinator import COORDINATOR_ALLOWED_TOOLS

    provider = RecordingProvider()
    monkeypatch.setattr(session_module, "new_provider", lambda _: provider)
    service.activate_provider(config())
    assert service.agent is not None
    names = {
        definition.name for definition in service.agent._registry.definitions()
    }
    assert names == set(COORDINATOR_ALLOWED_TOOLS)


class RecordingProvider:
    name = "fake"
    model = "main-model"

    def __init__(self, release: asyncio.Event | None = None) -> None:
        self.release = release

    async def stream(self, request: object):
        if self.release is not None:
            await self.release.wait()
        yield TextDelta("reply")
        yield StreamEnd("end")


def create_v2_session(path: Path, message: Message) -> None:
    journal = SessionJournal(path)
    journal.append_message(message)
    journal.close()
    SessionMetaStore(path).save(
        replace(SessionMeta.new(path.name), title=message.content, model="old-model")
    )


def find_info(tmp_path: Path, session_id: str):
    return next(
        item
        for item in list_sessions(str(tmp_path / ".Arkcode" / "sessions"))
        if item.id == session_id
    )


def test_activate_provider_creates_agent_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RecordingProvider()
    monkeypatch.setattr(session_module, "new_provider", lambda _: provider)
    service = make_service(tmp_path)

    service.activate_provider(config())

    assert service.provider is provider
    assert service.agent is not None
    assert service.agent.runtime is service.runtime
    assert service.skill_executor is not None
    assert service.runtime.context_window > 0
    assert service.mode == Mode.DEFAULT


def test_create_writes_format_v2_meta(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    meta = service.meta_store.load()

    assert meta is not None
    assert meta.format_version == 2
    assert meta.id == service.runtime.session.session_id


def test_clear_replaces_conversation_journal_and_meta_after_creation(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    old_conversation = service.conversation
    old_journal = service.journal
    old_meta = service.meta_store.load()
    old_id = service.runtime.session.session_id
    service.conversation.add_user("keep")

    service.clear_session()

    assert service.conversation is not old_conversation
    assert service.journal is not old_journal
    assert service.meta_store.load() != old_meta
    assert service.runtime.session.session_id != old_id
    assert service.conversation.messages() == []


def test_clear_failure_preserves_conversation_journal_and_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = make_service(tmp_path)
    old_conversation = service.conversation
    old_journal = service.journal
    service.conversation.add_user("keep")

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("disk failed")

    monkeypatch.setattr(session_module, "new_session_context", fail)

    with pytest.raises(RuntimeError, match="disk failed"):
        service.clear_session()

    assert service.conversation is old_conversation
    assert service.journal is old_journal
    assert service.conversation.messages()[0].content == "keep"


def test_resume_restores_without_reappend(tmp_path: Path) -> None:
    target = tmp_path / ".Arkcode" / "sessions" / "20260808-120000-abcd"
    create_v2_session(target, Message(role="user", content="恢复这段对话"))
    jsonl = target / "conversation.jsonl"
    before = jsonl.read_bytes()
    service = make_service(tmp_path)

    service.resume_session(find_info(tmp_path, target.name))

    assert service.runtime.session.session_id == target.name
    assert service.conversation.messages() == [
        Message(role="user", content="恢复这段对话")
    ]
    assert jsonl.read_bytes() == before


def test_resume_rejects_non_v2_session(tmp_path: Path) -> None:
    target = tmp_path / ".Arkcode" / "sessions" / "20260808-120000-abcd"
    target.mkdir(parents=True)
    (target / "conversation.jsonl").write_text(
        '{"role":"user","content":"legacy","ts":1}\n', encoding="utf-8"
    )
    service = make_service(tmp_path)

    from datetime import datetime

    from Arkcode.sessions.listing import SessionInfo

    with pytest.raises(ValueError, match="format v2"):
        service.resume_session(
            SessionInfo(
                id=target.name,
                title="legacy",
                modified_at=datetime.now(),
                model="",
                size=1,
                dir=str(target),
            )
        )


def test_provider_activation_saves_provider_and_model(tmp_path: Path) -> None:
    provider = RecordingProvider()
    service = make_service(tmp_path)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(session_module, "new_provider", lambda _: provider)
    try:
        service.activate_provider(config())
    finally:
        monkeypatch.undo()

    meta = service.meta_store.load()

    assert meta is not None
    assert meta.provider == "fake"
    assert meta.model == "main-model"


def test_cancel_sets_the_active_cancel_event(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.cancel_turn()

    assert service._cancel.is_set()


@pytest.mark.asyncio
async def test_submit_message_cancellation_ends_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()
    provider = RecordingProvider(release)
    monkeypatch.setattr(session_module, "new_provider", lambda _: provider)
    service = make_service(tmp_path)
    service.activate_provider(config())

    task = asyncio.create_task(_drain(service, "prompt"))
    await asyncio.sleep(0)
    service.cancel_turn()
    await task

    assert service.conversation.messages()[-1].content == NOTICE_CANCELLED


async def _drain(service: SessionService, text: str) -> None:
    async for _ in service.submit_message(text):
        pass
