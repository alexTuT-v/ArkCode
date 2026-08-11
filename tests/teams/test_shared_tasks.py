"""共享任务板测试。"""

from pathlib import Path

import pytest

from Arkcode.teams.models import SharedTaskStatus
from Arkcode.teams.shared_tasks import SharedTaskStore


def make_store(tmp_path: Path) -> SharedTaskStore:
    return SharedTaskStore(tmp_path / "team")


@pytest.mark.asyncio
async def test_create_get_list(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    task = await store.create("写文档", description="docs", assignee="alice")
    assert task.id.startswith("task_")
    got = await store.get(task.id)
    assert got is not None
    assert got.title == "写文档"
    tasks = await store.list_tasks()
    assert len(tasks) == 1


@pytest.mark.asyncio
async def test_blocked_by_blocks_bidirectional(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = await store.create("先做")
    second = await store.create("后做", blocked_by=[first.id])
    assert second.blocked_by == [first.id]
    first_reloaded = await store.get(first.id)
    assert first_reloaded is not None
    assert second.id in first_reloaded.blocks
    await store.update(first.id, status="completed")
    tasks = await store.list_tasks()
    second_reloaded = await store.get(second.id)
    assert second_reloaded is not None
    assert store.is_ready(second_reloaded, tasks) is True


@pytest.mark.asyncio
async def test_update_status_and_dependencies(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = await store.create("A")
    second = await store.create("B")
    updated = await store.update(
        first.id,
        status="in_progress",
        add_blocks=[second.id],
    )
    assert updated.status is SharedTaskStatus.IN_PROGRESS
    assert second.id in updated.blocks
    second_reloaded = await store.get(second.id)
    assert second_reloaded is not None
    assert first.id in second_reloaded.blocked_by
    removed = await store.update(first.id, remove_blocks=[second.id])
    assert removed.blocks == []
