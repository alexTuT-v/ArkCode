from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Arkcode.llm import Request, StreamEnd, TextDelta
from Arkcode.memory import Manager, Store, UpdateAction


def test_store_create_update_delete_note(tmp_path: Path) -> None:
    store = Store(str(tmp_path / "memory"))
    create = UpdateAction(
        action="create",
        level="project",
        type="project_knowledge",
        title="API 约定",
        slug="api_conventions",
        content="所有 API 返回统一 envelope。",
    )

    store.apply([create])

    note = tmp_path / "memory" / "project_knowledge_api_conventions.md"
    assert note.is_file()
    assert "type: project_knowledge" in note.read_text()
    assert "[project_knowledge] API 约定" in store.load_index()

    store.apply(
        [
            UpdateAction(
                action="update",
                level="project",
                filename=note.name,
                title="API 响应约定",
                content="API 返回 data/error envelope。",
            )
        ]
    )
    updated = note.read_text()
    assert "API 响应约定" in updated
    assert "API 返回 data/error envelope" in updated
    assert "created:" in updated and "updated:" in updated
    assert "API 响应约定" in store.load_index()

    store.apply([UpdateAction(action="delete", level="project", filename=note.name)])
    assert not note.exists()
    assert "API 响应约定" not in store.load_index()


def test_store_rejects_filename_escape(tmp_path: Path) -> None:
    store = Store(str(tmp_path / "memory"))

    with pytest.raises(ValueError):
        store.apply(
            [UpdateAction(action="delete", level="project", filename="../secret.md")]
        )


def test_manager_load_index_merges_project_first_and_truncates(tmp_path: Path) -> None:
    project = tmp_path / "project"
    user = tmp_path / "user"
    project.mkdir()
    user.mkdir()
    (project / "MEMORY.md").write_text("project index", encoding="utf-8")
    (user / "MEMORY.md").write_text("user index", encoding="utf-8")
    manager = Manager(str(project), str(user), None, "")

    assert manager.load_index() == "project index\n\nuser index"

    (project / "MEMORY.md").write_text("知" * 30_000, encoding="utf-8")
    truncated = manager.load_index()
    assert truncated.endswith("(index truncated)")
    assert len(truncated.encode("utf-8")) <= 25 * 1024


class MemoryProvider:
    name = "fake"
    model = "memory-model"

    def __init__(self) -> None:
        self.requests: list[Request] = []

    async def stream(self, req: Request) -> AsyncIterator[object]:
        self.requests.append(req)
        yield TextDelta(
            '[{"action":"create","level":"user",'
            '"type":"user_preference","title":"简洁回复",'
            '"slug":"terse_replies","content":"用户偏好简洁回复。"}]'
        )
        yield StreamEnd(stop_reason="end")


@pytest.mark.asyncio
async def test_manager_update_async_parses_response_without_tools(
    tmp_path: Path,
) -> None:
    provider = MemoryProvider()
    manager = Manager(
        str(tmp_path / "project"),
        str(tmp_path / "user"),
        provider,
        provider.model,
    )

    await manager.update_async([])

    note = tmp_path / "user" / "user_preference_terse_replies.md"
    assert note.is_file()
    assert provider.requests[0].tools is None
    assert provider.requests[0].system.stable


class BrokenMemoryProvider(MemoryProvider):
    async def stream(self, req: Request) -> AsyncIterator[object]:
        raise RuntimeError("memory unavailable")
        yield TextDelta("")


@pytest.mark.asyncio
async def test_manager_update_failure_does_not_escape(tmp_path: Path) -> None:
    provider = BrokenMemoryProvider()
    manager = Manager(
        str(tmp_path / "project"),
        str(tmp_path / "user"),
        provider,
        provider.model,
    )

    await manager.update_async([])

    assert not (tmp_path / "project" / "MEMORY.md").exists()
