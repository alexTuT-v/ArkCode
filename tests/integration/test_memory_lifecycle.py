"""自动提取、全文召回与 session JSONL 隔离的集成测试。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Arkcode.agents import Agent, SessionRuntime
from Arkcode.context import (
    CompactCircuitBreaker,
    RecoveryState,
    new_session_context,
)
from Arkcode.conversations import Conversation
from Arkcode.llm import Request, StreamEnd, StreamEvent, TextDelta
from Arkcode.memory import Manager
from Arkcode.memory.prompts import (
    MEMORY_EXTRACTION_SYSTEM_PROMPT,
    MEMORY_RECALL_SYSTEM_PROMPT,
)
from Arkcode.permissions import Mode
from Arkcode.sessions import SessionJournal
from Arkcode.tools import Registry


class MemoryLifecycleProvider:
    name = "fake"
    model = "memory-model"

    def __init__(self) -> None:
        self.main_requests: list[Request] = []
        self.extraction_calls = 0

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        if request.system.stable == MEMORY_EXTRACTION_SYSTEM_PROMPT:
            self.extraction_calls += 1
            if self.extraction_calls == 1:
                yield TextDelta(
                    '[{"action":"create","level":"user",'
                    '"type":"user_preference","title":"回答语言",'
                    '"slug":"response_language",'
                    '"content":"用户偏好使用中文回答。"}]'
                )
            else:
                yield TextDelta("[]")
        elif request.system.stable == MEMORY_RECALL_SYSTEM_PROMPT:
            yield TextDelta('["user:user_preference_response_language.md"]')
        else:
            self.main_requests.append(request)
            yield TextDelta("已按中文偏好回答。")
        yield StreamEnd("end")


async def drain_turn(
    agent: Agent,
    conversation: Conversation,
) -> None:
    async for _ in agent.run(conversation, Mode.NORMAL, asyncio.Event()):
        pass


@pytest.mark.asyncio
async def test_memory_lifecycle_does_not_append_internal_data_to_jsonl(
    tmp_path: Path,
) -> None:
    provider = MemoryLifecycleProvider()
    manager = Manager(
        str(tmp_path / "project-memory"),
        str(tmp_path / "user-memory"),
        provider,
        provider.model,
    )
    context = new_session_context(str(tmp_path))
    runtime = SessionRuntime(
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=context,
    )
    journal = SessionJournal(context.session_dir)
    conversation = Conversation(sink=journal)
    agent = Agent(
        provider,
        Registry(),
        runtime=runtime,
        memory_manager=manager,
    )
    jsonl = Path(journal.path)
    before_lines = jsonl.read_text(encoding="utf-8").splitlines()

    conversation.add_user("以后都用中文回答")
    await drain_turn(agent, conversation)
    await manager.flush_extraction()
    memory_file = tmp_path / "user-memory" / "user_preference_response_language.md"
    conversation.add_user("我偏好什么语言？")
    await drain_turn(agent, conversation)
    await manager.flush_extraction()
    journal.close()
    after_lines = jsonl.read_text(encoding="utf-8").splitlines()

    assert memory_file.exists()
    assert "用户偏好使用中文回答" in memory_file.read_text(encoding="utf-8")
    assert "Relevant long-term memories" in provider.main_requests[-1].reminder
    assert len(after_lines) == len(before_lines) + 4
    assert all('"action"' not in line for line in after_lines)
    assert all("Relevant long-term memories" not in line for line in after_lines)
