"""按需发现延迟加载工具的 ToolSearch 内置工具。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from ..base import Result, Tool

if TYPE_CHECKING:
    from ..registry import Registry


class Params(BaseModel):
    query: str = Field(
        description="搜索关键词，或以 select:<name>[,<name>...] 精确加载"
    )
    max_results: int = Field(default=5, description="返回结果上限")


class ToolSearchTool(Tool[Params]):
    """搜索并加载未立即可用的延迟工具。"""

    read_only = True
    should_defer = False
    params_model = Params

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def name(self) -> str:
        return "ToolSearch"

    def description(self) -> str:
        return (
            "搜索并加载当前不可用的延迟工具；"
            "使用 select:<name>[,<name>...] 按名加载，或提供关键词搜索"
        )

    async def execute(self, params: Params) -> Result:
        query = params.query
        if query.startswith("select:"):
            names = [item.strip() for item in query[7:].split(",") if item.strip()]
            schemas = self._registry.find_deferred_by_names(names)
        else:
            schemas = self._registry.search_deferred(query, params.max_results)
        if not schemas:
            deferred = self._registry.get_deferred_tool_names()
            return Result(
                content=(
                    f'No matching deferred tools for "{query}". '
                    f"Available: {', '.join(deferred)}"
                )
            )
        for schema in schemas:
            if "name" in schema:
                self._registry.mark_discovered(schema["name"])
        return Result(
            content=(
                f"Found {len(schemas)} tool(s). "
                "Their full schemas are now loaded:\n\n"
                f"{json.dumps(schemas, indent=2, ensure_ascii=False)}"
            )
        )
