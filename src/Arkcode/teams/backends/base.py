"""Backend Protocol 与通用类型。"""

from __future__ import annotations

from typing import Protocol

from ..models import BackendType, SpawnRequest, SpawnResult


class Backend(Protocol):
    def type(self) -> BackendType: ...

    async def spawn(self, request: SpawnRequest) -> SpawnResult: ...

    async def wake(self, pane_id: str, agent_id: str) -> None: ...

    async def kill(self, pane_id: str, agent_id: str) -> None: ...

    async def is_alive(self, pane_id: str, agent_id: str) -> bool: ...
