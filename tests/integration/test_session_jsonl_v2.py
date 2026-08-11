"""格式 v2 会话日志的线性增长与压缩边界集成测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from Arkcode.application import SessionService
from Arkcode.llm import (
    Message,
    Request,
    StreamEnd,
    StreamEvent,
    TextDelta,
    ToolCallComplete,
)
from Arkcode.permissions import new_engine
from Arkcode.sessions import (
    decode_record,
    list_sessions,
)
from Arkcode.sessions.record import CompactBoundary
from Arkcode.skills import SkillLoader
from Arkcode.tools import Result, new_default_registry
from Arkcode.tools.base import Tool


class _Params(BaseModel):
    pass


class EchoTool(Tool[_Params]):
    read_only = True
    should_defer = False
    params_model = _Params

    def name(self) -> str:
        return "echo_tool"

    def description(self) -> str:
        return "echo tool"

    async def execute(self, params: _Params) -> Result:
        return Result("echoed")


class ToolLoopProvider:
    """先执行几次确定性工具循环，再返回最终文本。"""

    name = "fake"
    model = "fake-model"

    def __init__(self, loops: int = 3) -> None:
        self.loops = loops
        self.requests: list[Request] = []

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        for index in range(self.loops):
            yield ToolCallComplete(
                tool_id=f"call-{index}",
                tool_name="echo_tool",
                arguments={},
            )
            yield StreamEnd("tool_use", 10, 2)
        yield TextDelta("完成")
        yield StreamEnd("end_turn", 10, 2)


class CompactProvider:
    """第一次主请求先触发一次真实摘要，随后工具循环并完成。"""

    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.requests: list[Request] = []

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        if req.tools is None:
            yield TextDelta("<summary>compressed</summary>")
            yield StreamEnd("stop")
            return
        if len(self.requests) == 1:
            yield ToolCallComplete("c1", "echo_tool", {})
            yield StreamEnd("tool_use")
            return
        yield TextDelta("done")
        yield StreamEnd("end_turn")


def make_service(tmp_path: Path, provider: Any, window: int = 60000) -> SessionService:
    engine, error = new_engine(str(tmp_path))
    assert error is None
    registry = new_default_registry()
    registry.register(EchoTool())
    skills = SkillLoader(tmp_path)
    skills.load_all()
    service = SessionService(
        workspace=tmp_path,
        version="0.1.0",
        registry=registry,
        permissions=engine,
        skills=skills,
    )
    service.provider = provider
    service.runtime.context_window = window
    return service


async def _drain(service: SessionService, text: str) -> None:
    async for _ in service.submit_message(text):
        pass


@pytest.mark.asyncio
async def test_records_equal_messages_without_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import Arkcode.application.session as session_module

    provider = ToolLoopProvider(loops=3)
    monkeypatch.setattr(session_module, "new_provider", lambda _: provider)
    service = make_service(tmp_path, provider)
    from Arkcode.config import ProviderConfig

    service.activate_provider(
        ProviderConfig(name="fake", protocol="openai", api_key="x", model="m")
    )

    await _drain(service, "跑三轮工具")
    jsonl = Path(service.journal.path)
    records = [decode_record(line) for line in jsonl.read_text().splitlines()]
    messages = [record for record in records if isinstance(record, Message)]
    boundaries = [record for record in records if isinstance(record, CompactBoundary)]

    assert messages == service.conversation.messages()
    assert boundaries == []
    assert len(records) == len(messages)


@pytest.mark.asyncio
async def test_successful_compaction_appends_exactly_one_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import Arkcode.application.session as session_module

    provider = CompactProvider()
    monkeypatch.setattr(session_module, "new_provider", lambda _: provider)
    service = make_service(tmp_path, provider, window=40000)
    from Arkcode.config import ProviderConfig

    service.activate_provider(
        ProviderConfig(name="fake", protocol="openai", api_key="x", model="m")
    )
    service.runtime.context_window = 40000
    service.conversation.replace_history(
        [Message(role="user", content="old" * 30000)]
        + [Message(role="assistant", content="x" * 7000) for _ in range(5)]
    )

    await _drain(service, "触发一次压缩")
    jsonl = Path(service.journal.path)
    lines = jsonl.read_text().splitlines()
    records = [decode_record(line) for line in lines]
    messages = [record for record in records if isinstance(record, Message)]
    boundaries = [record for record in records if isinstance(record, CompactBoundary)]

    assert len(boundaries) == 1
    assert len(lines) == len(messages) + len(boundaries)
    assert all("old" not in message.content for message in messages)
    assert messages[0].content == "触发一次压缩"


@pytest.mark.asyncio
async def test_resume_extends_without_reappending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import Arkcode.application.session as session_module

    provider = ToolLoopProvider(loops=2)
    monkeypatch.setattr(session_module, "new_provider", lambda _: provider)
    service = make_service(tmp_path, provider)
    from Arkcode.config import ProviderConfig

    service.activate_provider(
        ProviderConfig(name="fake", protocol="openai", api_key="x", model="m")
    )
    await _drain(service, "第一段对话")
    jsonl = Path(service.journal.path)
    before = jsonl.read_bytes()

    info = next(
        item
        for item in list_sessions(service.sessions_dir)
        if item.id == service.runtime.session.session_id
    )
    service.resume_session(info)
    await _drain(service, "继续旧会话")

    after = jsonl.read_bytes()
    assert after.startswith(before)
    assert len(after) > len(before)
    records = [decode_record(line) for line in after.decode().splitlines()]
    assert sum(isinstance(record, Message) for record in records) == len(
        [record for record in records if isinstance(record, Message)]
    )
