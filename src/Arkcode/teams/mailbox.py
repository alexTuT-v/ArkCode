"""按收件人分文件的邮箱读写与广播。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .models import Message
from .storage import FileLock, atomic_update_json


class Box:
    def __init__(self, team_config_dir: str | Path) -> None:
        self._directory = Path(team_config_dir) / "mailbox"
        self._directory.mkdir(parents=True, exist_ok=True)

    def _path(self, agent_id: str) -> Path:
        return self._directory / f"{agent_id}.json"

    def _lock(self, agent_id: str) -> FileLock:
        return FileLock(self._directory / f"{agent_id}.json.lock")

    async def write(self, agent_id: str, message: Message) -> None:
        await asyncio.to_thread(self._write_sync, agent_id, message)

    def _write_sync(self, agent_id: str, message: Message) -> None:
        path = self._path(agent_id)

        def mutate(value: object) -> list[dict[str, object]]:
            messages = (
                [Message.from_dict(item) for item in value]
                if isinstance(value, list)
                else []
            )
            messages.append(message)
            return [item.to_dict() for item in messages]

        atomic_update_json(path, self._lock(agent_id), mutate)

    async def read(self, agent_id: str) -> list[Message]:
        return await asyncio.to_thread(self._read_sync, agent_id)

    def _read_sync(self, agent_id: str) -> list[Message]:
        path = self._path(agent_id)
        if not path.is_file():
            return []
        try:
            value = atomic_update_json(
                path,
                self._lock(agent_id),
                lambda current: current,
            )
        except Exception:
            return []
        if not isinstance(value, list):
            return []
        return [Message.from_dict(item) for item in value if isinstance(item, dict)]

    async def mark_read(self, agent_id: str, indexes: list[int]) -> None:
        await asyncio.to_thread(self._mark_read_sync, agent_id, indexes)

    def _mark_read_sync(self, agent_id: str, indexes: list[int]) -> None:
        path = self._path(agent_id)
        wanted = set(indexes)

        def mutate(value: object) -> list[dict[str, object]]:
            messages = (
                [Message.from_dict(item) for item in value]
                if isinstance(value, list)
                else []
            )
            for index, message in enumerate(messages):
                if index in wanted:
                    message.read = True
            return [item.to_dict() for item in messages]

        atomic_update_json(path, self._lock(agent_id), mutate)

    async def broadcast(
        self,
        from_agent: str,
        targets: list[str],
        message: Message,
    ) -> None:
        for agent_id in targets:
            if agent_id == from_agent:
                continue
            await self.write(agent_id, message)
