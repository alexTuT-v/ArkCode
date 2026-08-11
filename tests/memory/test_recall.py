"""选择性长期记忆召回测试。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Arkcode.llm import Request, StreamEnd, StreamError, StreamEvent, TextDelta
from Arkcode.memory import Store, UpdateAction
from Arkcode.memory.recall import Recall


class RecallProvider:
    name = "fake"
    model = "recall-model"

    def __init__(
        self,
        response: str = "[]",
        *,
        error: Exception | None = None,
        delay: float = 0,
    ) -> None:
        self.response = response
        self.error = error
        self.delay = delay
        self.requests: list[Request] = []

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            yield StreamError(self.error)
            return
        yield TextDelta(self.response)
        yield StreamEnd("end")


def create_note(
    store: Store,
    *,
    slug: str,
    content: str,
) -> str:
    store.apply(
        [
            UpdateAction(
                action="create",
                level="user",
                type="user_preference",
                title=f"记忆 {slug}",
                slug=slug,
                content=content,
            )
        ]
    )
    return f"user_preference_{slug}.md"


def make_recall(
    tmp_path: Path,
    provider: RecallProvider,
    *,
    timeout: float = 5.0,
) -> tuple[Recall, Store, Store]:
    project = Store(str(tmp_path / "project"))
    user = Store(str(tmp_path / "user"))
    return (
        Recall(project, user, provider, provider.model, timeout_seconds=timeout),
        project,
        user,
    )


@pytest.mark.asyncio
async def test_recall_reads_only_unique_known_keys(tmp_path: Path) -> None:
    provider = RecallProvider(
        json.dumps(
            [
                "user:user_preference_language.md",
                "user:user_preference_language.md",
                "user:../../secret.md",
            ]
        )
    )
    recall, _, user = make_recall(tmp_path, provider)
    create_note(user, slug="language", content="用户偏好中文回答。")

    text = await recall.select("应该用什么语言回答？")

    assert text.count("用户偏好中文回答") == 1
    assert "../../secret.md" not in text


@pytest.mark.asyncio
async def test_recall_limits_selection_to_five(tmp_path: Path) -> None:
    keys = [f"user:user_preference_memory_{index}.md" for index in range(6)]
    provider = RecallProvider(json.dumps(keys))
    recall, _, user = make_recall(tmp_path, provider)
    for index in range(6):
        create_note(user, slug=f"memory_{index}", content=str(index) * 4_000)

    text = await recall.select("相关内容")

    assert text.count("<memory key=") == 5
    assert "user:user_preference_memory_5.md" not in text


@pytest.mark.asyncio
async def test_recall_truncates_total_output_to_25_kib(tmp_path: Path) -> None:
    provider = RecallProvider('["user:user_preference_large.md"]')
    recall, _, user = make_recall(tmp_path, provider)
    create_note(user, slug="large", content="长" * 20_000)

    text = await recall.select("大记忆")

    assert len(text.encode("utf-8")) <= 25 * 1024
    assert "(memory truncated)" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["invalid-json", "stream-error", "timeout"])
async def test_recall_failure_returns_empty_text(
    tmp_path: Path,
    failure: str,
) -> None:
    if failure == "invalid-json":
        provider = RecallProvider("not json")
        timeout = 5.0
    elif failure == "stream-error":
        provider = RecallProvider(error=RuntimeError("unavailable"))
        timeout = 5.0
    else:
        provider = RecallProvider(delay=0.1)
        timeout = 0.01
    recall, _, user = make_recall(tmp_path, provider, timeout=timeout)
    create_note(user, slug="language", content="中文。")

    assert await recall.select("query") == ""


@pytest.mark.asyncio
async def test_recall_skips_provider_when_manifest_is_empty(tmp_path: Path) -> None:
    provider = RecallProvider()
    recall, _, _ = make_recall(tmp_path, provider)

    assert await recall.select("query") == ""
    assert provider.requests == []
