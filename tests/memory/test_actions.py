"""记忆 JSON action 解析、校验与执行测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Arkcode.llm import Request, StreamEnd, StreamError, StreamEvent, TextDelta
from Arkcode.memory.actions import MemoryActionService, parse_actions
from Arkcode.memory.store import Store


class TextProvider:
    name = "fake"
    model = "memory-model"

    def __init__(self, value: str | Exception) -> None:
        self.value = value
        self.requests: list[Request] = []

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        if isinstance(self.value, Exception):
            yield StreamError(self.value)
            return
        yield TextDelta(self.value)
        yield StreamEnd("end")


def action_service(
    tmp_path: Path,
    value: str | Exception,
) -> tuple[MemoryActionService, TextProvider]:
    provider = TextProvider(value)
    return (
        MemoryActionService(
            Store(str(tmp_path / "project")),
            Store(str(tmp_path / "user")),
            provider,
            provider.model,
        ),
        provider,
    )


def test_parse_accepts_plain_array_and_single_json_fence() -> None:
    raw = (
        '[{"action":"delete","level":"user",'
        '"type":"user_preference",'
        '"filename":"user_preference_old.md"}]'
    )

    assert parse_actions(raw)[0].action == "delete"
    assert parse_actions(f"```json\n{raw}\n```") == parse_actions(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        "[1]",
        "[] []",
        '[{"action":"erase","level":"user","type":"user_preference"}]',
        (
            '[{"action":"delete","level":"users",'
            '"type":"user_preference",'
            '"filename":"user_preference_old.md"}]'
        ),
        (
            '[{"action":"delete","level":"user",'
            '"type":"project_knowledge",'
            '"filename":"user_preference_old.md"}]'
        ),
    ],
)
def test_parse_rejects_invalid_batch(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_actions(raw)


@pytest.mark.asyncio
async def test_validation_happens_before_any_store_write(tmp_path: Path) -> None:
    service, _ = action_service(
        tmp_path,
        (
            '[{"action":"create","level":"user",'
            '"type":"user_preference","title":"语言","slug":"language",'
            '"content":"中文"},{"action":"delete","level":"user",'
            '"type":"user_preference","filename":"../bad.md"}]'
        ),
    )

    assert await service.execute("prompt", {}) is False
    assert not list((tmp_path / "project").glob("*.md"))
    assert not list((tmp_path / "user").glob("*.md"))


@pytest.mark.asyncio
async def test_service_routes_valid_actions_without_tools(tmp_path: Path) -> None:
    service, provider = action_service(
        tmp_path,
        (
            '[{"action":"create","level":"project",'
            '"type":"project_knowledge","title":"架构",'
            '"slug":"architecture","content":"分层设计。"},'
            '{"action":"create","level":"user",'
            '"type":"user_preference","title":"语言",'
            '"slug":"language","content":"中文。"}]'
        ),
    )

    assert await service.execute("prompt", {"turns": []}) is True
    assert (tmp_path / "project" / "project_knowledge_architecture.md").exists()
    assert (tmp_path / "user" / "user_preference_language.md").exists()
    assert provider.requests[0].tools is None


@pytest.mark.asyncio
async def test_empty_array_is_success_without_writing_files(tmp_path: Path) -> None:
    service, _ = action_service(tmp_path, "[]")

    assert await service.execute("prompt", {}) is True
    assert not (tmp_path / "project").exists()
    assert not (tmp_path / "user").exists()


@pytest.mark.asyncio
async def test_stream_error_returns_false(tmp_path: Path) -> None:
    service, _ = action_service(tmp_path, RuntimeError("memory unavailable"))

    assert await service.execute("prompt", {}) is False
