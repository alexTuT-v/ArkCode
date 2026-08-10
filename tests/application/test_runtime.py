"""ApplicationRuntime 装配与关闭顺序测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from Arkcode.application import ApplicationRuntime
from Arkcode.config import Config
from Arkcode.mcp import McpStatus
from Arkcode.tools import Registry


class FakeSession:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def shutdown(self) -> None:
        self.calls.append("writer")


class FakeMemory:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def shutdown(self) -> None:
        self.calls.append("memory")


class FakeMcp:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def close(self) -> None:
        self.calls.append("mcp")


async def _record_cleanup(calls: list[str]) -> None:
    calls.append("tasks")


def make_runtime(
    calls: list[str],
    cleanup_task: asyncio.Task[None] | None = None,
) -> ApplicationRuntime:
    return ApplicationRuntime(
        workspace=Path("/workspace"),
        version="0.1.0",
        config=Config(providers=[]),
        tools=Registry(),
        permissions=object(),  # type: ignore[arg-type]
        mcp=FakeMcp(calls),  # type: ignore[arg-type]
        mcp_status=McpStatus(0, 0, 0),
        memory=FakeMemory(calls),  # type: ignore[arg-type]
        skills=object(),  # type: ignore[arg-type]
        session=FakeSession(calls),  # type: ignore[arg-type]
        cleanup_task=cleanup_task,
    )


@pytest.mark.asyncio
async def test_shutdown_closes_session_then_memory_then_tasks_then_mcp() -> None:
    calls: list[str] = []
    cleanup_task = asyncio.create_task(_record_cleanup(calls))
    runtime = make_runtime(calls, cleanup_task)

    await runtime.shutdown()

    assert calls == ["writer", "memory", "tasks", "mcp"]


@pytest.mark.asyncio
async def test_shutdown_skips_missing_cleanup_task() -> None:
    calls: list[str] = []
    runtime = make_runtime(calls)

    await runtime.shutdown()

    assert calls == ["writer", "memory", "mcp"]
