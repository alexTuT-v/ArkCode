"""工具注册、发现和受控执行。"""

import asyncio
from collections.abc import Collection
from typing import Any

from pydantic import ValidationError

from .base import Result, Tool, ToolDefinition

DEFAULT_TIMEOUT = 30.0


class Registry:
    """集中登记、发现并安全执行工具。"""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._tools: dict[str, Tool[Any]] = {}
        self._discovered: set[str] = set()
        self._timeouts: dict[str, float | None] = {}

    def set_timeout(self, name: str, timeout: float | None) -> None:
        """为单个工具覆盖默认执行超时；None 表示不限时。"""

        self._timeouts[name] = timeout

    def disable_timeout(self, name: str) -> None:
        self._timeouts[name] = None

    def timeout_for(self, name: str) -> float | None:
        return self._timeouts.get(name)

    def mark_discovered(self, name: str) -> None:
        self._discovered.add(name)

    def is_discovered(self, name: str) -> bool:
        return name in self._discovered

    def _is_deferred(self, tool: Tool[Any]) -> bool:
        return bool(getattr(tool, "should_defer", False))

    def get_deferred_tool_names(self) -> list[str]:
        return [
            name
            for name in self._order
            if self._is_deferred(self._tools[name]) and name not in self._discovered
        ]

    def search_deferred(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        query_lower = query.strip().lower()
        if not query_lower:
            return []
        query_words = query_lower.split()
        scored: list[tuple[int, str, Tool[Any]]] = []
        for name in self._order:
            tool = self._tools[name]
            if not self._is_deferred(tool) or name in self._discovered:
                continue
            name_lower = name.lower()
            description_lower = (tool.description() or "").lower()
            score = 0
            if query_lower in name_lower:
                score += 10
            if query_lower in description_lower:
                score += 5
            for word in query_words:
                if word in name_lower:
                    score += 3
                if word in description_lower:
                    score += 1
            if score > 0:
                scored.append((score, name, tool))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [tool.get_schema() for _, _, tool in scored[:max_results]]

    def find_deferred_by_names(self, names: list[str]) -> list[dict[str, Any]]:
        return [
            self._tools[name].get_schema()
            for name in names
            if name in self._tools
            and self._is_deferred(self._tools[name])
            and name not in self._discovered
        ]

    def register(self, tool: Tool[Any]) -> None:
        name = tool.name()
        if name in self._tools:
            raise ValueError(f"工具已注册: {name}")
        self._order.append(name)
        self._tools[name] = tool

    def get(self, name: str) -> Tool[Any] | None:
        return self._tools.get(name)

    def without(self, names: Collection[str]) -> "Registry":
        """返回排除指定工具的独立注册表，并保留其余工具顺序。"""

        excluded = set(names)
        filtered = Registry()
        for name in self._order:
            if name not in excluded:
                filtered.register(self._tools[name])
        return filtered

    def count(self) -> int:
        return len(self._tools)

    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=name,
                description=self._tools[name].description(),
                input_schema=self._tools[name].get_schema()["input_schema"],
            )
            for name in self._order
            if not self._is_deferred(self._tools[name]) or name in self._discovered
        ]

    def read_only_definitions(self) -> list[ToolDefinition]:
        """按注册顺序导出可在 Plan Mode 使用的只读工具。"""

        return [
            ToolDefinition(
                name=name,
                description=self._tools[name].description(),
                input_schema=self._tools[name].get_schema()["input_schema"],
            )
            for name in self._order
            if self._tools[name].read_only
            and (not self._is_deferred(self._tools[name]) or name in self._discovered)
        ]

    def is_read_only(self, name: str) -> bool:
        """判断已注册工具是否为只读；未知工具返回 False。"""

        tool = self.get(name)
        return tool is not None and tool.read_only

    async def execute(
        self,
        name: str,
        args: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Result:
        tool = self.get(name)
        if tool is None:
            return Result(content=f"未知工具: {name}", is_error=True)
        try:
            params = tool.params_model.model_validate_json(args)
        except ValidationError as exc:
            return Result(content=f"参数校验失败: {exc}", is_error=True)
        try:
            timeout_override = self._timeouts.get(name)
            effective_timeout = (
                timeout_override
                if timeout_override is not None
                else timeout
            )
            if effective_timeout is None:
                return await tool.execute(params)
            return await asyncio.wait_for(
                tool.execute(params),
                timeout=effective_timeout,
            )
        except TimeoutError:
            return Result(content=f"工具 {name} 执行超时（{timeout}s）", is_error=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return Result(content=f"工具 {name} 异常: {exc}", is_error=True)
