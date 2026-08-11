"""共享任务板：tasks.json 的完整锁内 read-modify-write。"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from .models import SharedTask, SharedTaskStatus
from .storage import FileLock, atomic_update_json


class SharedTaskStore:
    def __init__(self, team_config_dir: str | Path) -> None:
        self._path = Path(team_config_dir) / "tasks.json"
        self._lock = FileLock(Path(team_config_dir) / "tasks.lock")

    def _load(self, value: object) -> list[SharedTask]:
        if not isinstance(value, dict):
            return []
        tasks = value.get("tasks", [])
        if not isinstance(tasks, list):
            return []
        return [
            SharedTask.from_dict(item) for item in tasks if isinstance(item, dict)
        ]

    async def create(
        self,
        title: str,
        *,
        description: str = "",
        assignee: str = "",
        blocked_by: list[str] | None = None,
    ) -> SharedTask:
        return await asyncio.to_thread(
            self._create_sync,
            title,
            description,
            assignee,
            blocked_by or [],
        )

    def _create_sync(
        self,
        title: str,
        description: str,
        assignee: str,
        blocked_by: list[str],
    ) -> SharedTask:
        now = int(time.time())

        def mutate(value: object) -> dict[str, object]:
            tasks = self._load(value)
            existing = {task.id: task for task in tasks}
            task = SharedTask(
                id=f"task_{uuid.uuid4().hex[:6]}",
                title=title,
                description=description,
                status=SharedTaskStatus.PENDING,
                assignee=assignee,
                blocked_by=[],
                blocks=[],
                created_at=now,
                updated_at=now,
            )
            tasks.append(task)
            self._sync_dependencies(tasks, existing)
            for blocker_id in blocked_by:
                blocker = existing.get(blocker_id)
                if blocker is not None:
                    task.blocked_by.append(blocker_id)
                    if task.id not in blocker.blocks:
                        blocker.blocks.append(task.id)
                    blocker.updated_at = now
            return {"tasks": [item.to_dict() for item in tasks]}

        updated = atomic_update_json(self._path, self._lock, mutate)
        tasks = self._load(updated)
        return tasks[-1]

    def _sync_dependencies(
        self,
        tasks: list[SharedTask],
        existing: dict[str, SharedTask],
    ) -> None:
        for task in tasks:
            task.blocks = [
                other.id
                for other in tasks
                if task.id in other.blocked_by
            ]

    async def get(self, task_id: str) -> SharedTask | None:
        return await asyncio.to_thread(self._get_sync, task_id)

    def _get_sync(self, task_id: str) -> SharedTask | None:
        value = atomic_update_json(
            self._path,
            self._lock,
            lambda current: current,
        )
        return next(
            (task for task in self._load(value) if task.id == task_id),
            None,
        )

    async def list_tasks(self, status: str | None = None) -> list[SharedTask]:
        return await asyncio.to_thread(self._list_sync, status)

    def _list_sync(self, status: str | None) -> list[SharedTask]:
        value = atomic_update_json(
            self._path,
            self._lock,
            lambda current: current,
        )
        tasks = self._load(value)
        if status:
            return [task for task in tasks if task.status.value == status]
        return tasks

    async def update(self, task_id: str, **fields: object) -> SharedTask:
        return await asyncio.to_thread(self._update_sync, task_id, fields)

    def _update_sync(
        self,
        task_id: str,
        fields: dict[str, object],
    ) -> SharedTask:
        now = int(time.time())

        def mutate(value: object) -> dict[str, object]:
            tasks = self._load(value)
            target = next((task for task in tasks if task.id == task_id), None)
            if target is None:
                raise KeyError(f"未知 task_id: {task_id}")
            if "title" in fields and isinstance(fields["title"], str):
                target.title = fields["title"]
            if "description" in fields and isinstance(fields["description"], str):
                target.description = fields["description"]
            if "assignee" in fields and isinstance(fields["assignee"], str):
                target.assignee = fields["assignee"]
            if "status" in fields and isinstance(fields["status"], str):
                try:
                    target.status = SharedTaskStatus(fields["status"])
                except ValueError:
                    raise ValueError(f"非法状态: {fields['status']}")
            self._apply_dependency_edits(tasks, target, fields)
            target.updated_at = now
            return {"tasks": [item.to_dict() for item in tasks]}

        updated = atomic_update_json(self._path, self._lock, mutate)
        tasks = self._load(updated)
        target = next((task for task in tasks if task.id == task_id), None)
        if target is None:
            raise KeyError(f"未知 task_id: {task_id}")
        return target

    def _apply_dependency_edits(
        self,
        tasks: list[SharedTask],
        target: SharedTask,
        fields: dict[str, object],
    ) -> None:
        by_id = {task.id: task for task in tasks}
        for key, suffix in (
            ("add_blocked_by", "blocked_by"),
            ("add_blocks", "blocks"),
            ("remove_blocked_by", "blocked_by"),
            ("remove_blocks", "blocks"),
        ):
            raw = fields.get(key)
            if not isinstance(raw, list):
                continue
            values = [str(item) for item in raw]
            if key.startswith("add_"):
                for other_id in values:
                    other = by_id.get(other_id)
                    if other is None:
                        continue
                    if suffix == "blocked_by":
                        if other_id not in target.blocked_by:
                            target.blocked_by.append(other_id)
                        if target.id not in other.blocks:
                            other.blocks.append(target.id)
                    else:
                        if other_id not in target.blocks:
                            target.blocks.append(other_id)
                        if target.id not in other.blocked_by:
                            other.blocked_by.append(target.id)
            else:
                if suffix == "blocked_by":
                    target.blocked_by = [
                        item for item in target.blocked_by if item not in values
                    ]
                    for other_id in values:
                        other = by_id.get(other_id)
                        if other is not None and target.id in other.blocks:
                            other.blocks.remove(target.id)
                else:
                    target.blocks = [
                        item for item in target.blocks if item not in values
                    ]
                    for other_id in values:
                        other = by_id.get(other_id)
                        if other is not None and target.id in other.blocked_by:
                            other.blocked_by.remove(target.id)
        self._sync_dependencies(tasks, by_id)

    def is_ready(self, task: SharedTask, all_tasks: list[SharedTask]) -> bool:
        by_id = {item.id: item for item in all_tasks}
        return all(
            by_id.get(blocker) is not None
            and by_id[blocker].status is SharedTaskStatus.COMPLETED
            for blocker in task.blocked_by
        )
