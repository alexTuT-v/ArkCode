import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Arkcode.llm import Request, StreamEnd, StreamEvent, TextDelta
from Arkcode.memory import Manager, MemoryTurn, UpdateAction


class SequenceProvider:
    name = "fake"
    model = "memory-model"

    def __init__(self, values: list[str | Exception]) -> None:
        self.values = values
        self.call_count = 0
        self.payloads: list[dict[str, object]] = []
        self.active = 0
        self.peak_active = 0

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.call_count += 1
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        self.payloads.append(json.loads(request.messages[0].content))
        try:
            value = self.values[self.call_count - 1]
            if isinstance(value, Exception):
                raise value
            yield TextDelta(value)
            yield StreamEnd("end")
        finally:
            self.active -= 1


class BlockingSequenceProvider(SequenceProvider):
    def __init__(self, values: list[str | Exception]) -> None:
        super().__init__(values)
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.call_count += 1
        call_index = self.call_count - 1
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        self.payloads.append(json.loads(request.messages[0].content))
        try:
            if call_index == 0:
                self.first_started.set()
                await self.release_first.wait()
            value = self.values[call_index]
            if isinstance(value, Exception):
                raise value
            yield TextDelta(value)
            yield StreamEnd("end")
        finally:
            self.active -= 1


def turn(turn_id: str, user: str, assistant: str) -> MemoryTurn:
    return MemoryTurn(
        session_id="session-1",
        turn_id=turn_id,
        user_text=user,
        assistant_text=assistant,
    )


def make_manager(tmp_path: Path, provider: SequenceProvider) -> Manager:
    return Manager(
        str(tmp_path / "project"),
        str(tmp_path / "user"),
        provider,
        provider.model,
    )


def test_list_files_sorts_markdown_files_at_both_levels(tmp_path: Path) -> None:
    project = tmp_path / "project"
    user = tmp_path / "user"
    project.mkdir()
    user.mkdir()
    for path in (project / "z.md", project / "MEMORY.md", user / "a.md"):
        path.write_text("note", encoding="utf-8")
    (project / "ignore.txt").write_text("no", encoding="utf-8")

    manager = Manager(str(project), str(user), None, "")

    assert manager.list_files() == (["MEMORY.md", "z.md"], ["a.md"])


@pytest.mark.asyncio
async def test_extract_coalesces_turns_arriving_while_active(tmp_path: Path) -> None:
    provider = BlockingSequenceProvider(["[]", "[]"])
    manager = make_manager(tmp_path, provider)
    manager.schedule_extract(turn("t1", "用户一", "回答一"))
    await provider.first_started.wait()
    manager.schedule_extract(turn("t2", "用户二", "回答二"))
    manager.schedule_extract(turn("t3", "用户三", "回答三"))

    provider.release_first.set()
    await manager.flush_extraction()

    assert provider.peak_active == 1
    assert [item["turn_id"] for item in provider.payloads[0]["turns"]] == ["t1"]
    assert [item["turn_id"] for item in provider.payloads[1]["turns"]] == [
        "t2",
        "t3",
    ]


@pytest.mark.asyncio
async def test_extract_retries_failed_batch_once_on_next_trigger(
    tmp_path: Path,
) -> None:
    provider = SequenceProvider([RuntimeError("down"), "[]", "[]"])
    manager = make_manager(tmp_path, provider)
    manager.schedule_extract(turn("old", "旧问题", "旧回答"))
    first_task = manager._extract_task
    assert first_task is not None
    await first_task
    assert manager.has_pending_extraction()

    manager.schedule_extract(turn("new", "新问题", "新回答"))
    await manager.flush_extraction()

    assert provider.call_count == 3
    assert provider.payloads[1]["turns"][0]["turn_id"] == "old"
    assert provider.payloads[2]["turns"][0]["turn_id"] == "new"
    assert not manager.has_pending_extraction()


@pytest.mark.asyncio
async def test_twice_failed_batch_does_not_block_new_turn(tmp_path: Path) -> None:
    provider = SequenceProvider([RuntimeError("down-1"), RuntimeError("down-2"), "[]"])
    manager = make_manager(tmp_path, provider)
    manager.schedule_extract(turn("old", "旧问题", "旧回答"))
    first_task = manager._extract_task
    assert first_task is not None
    await first_task

    manager.schedule_extract(turn("new", "新问题", "新回答"))
    await manager.flush_extraction()

    assert provider.call_count == 3
    assert provider.payloads[2]["turns"][0]["turn_id"] == "new"
    assert not manager.has_pending_extraction()


@pytest.mark.asyncio
async def test_manager_recall_reads_selected_memory(tmp_path: Path) -> None:
    provider = SequenceProvider('["user:user_preference_language.md"]'.splitlines())
    manager = make_manager(tmp_path, provider)
    manager.user_store.apply(
        [
            UpdateAction(
                action="create",
                level="user",
                type="user_preference",
                title="语言",
                slug="language",
                content="用户偏好中文回答。",
            )
        ]
    )

    recalled = await manager.recall("用什么语言？")

    assert "用户偏好中文回答" in recalled


@pytest.mark.asyncio
async def test_manager_shutdown_limits_extraction_wait_to_three_seconds(
    tmp_path: Path,
) -> None:
    provider = BlockingSequenceProvider(["[]"])
    manager = make_manager(tmp_path, provider)
    manager.schedule_extract(turn("slow", "问题", "回答"))
    await provider.first_started.wait()
    loop = asyncio.get_running_loop()

    started = loop.time()
    await manager.shutdown()
    elapsed = loop.time() - started

    assert 2.8 <= elapsed < 3.5
    assert manager._extract_task is None
