"""Agent 名称注册表（线程安全，后注册覆盖）。"""

from __future__ import annotations

import threading


class AgentNameRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.by_name: dict[str, str] = {}
        self.by_id: dict[str, str] = {}

    def register(self, name: str, agent_id: str) -> None:
        with self._lock:
            self.by_name[name] = agent_id
            self.by_id[agent_id] = name

    def unregister(self, name: str) -> None:
        with self._lock:
            agent_id = self.by_name.pop(name, None)
            if agent_id is not None and self.by_id.get(agent_id) == name:
                self.by_id.pop(agent_id, None)

    def resolve(self, name_or_id: str) -> str | None:
        with self._lock:
            if name_or_id in self.by_name:
                return self.by_name[name_or_id]
            if name_or_id in self.by_id:
                return name_or_id
            return None

    def name_of(self, agent_id: str) -> str | None:
        with self._lock:
            return self.by_id.get(agent_id)
