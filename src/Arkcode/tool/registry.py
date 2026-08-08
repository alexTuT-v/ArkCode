"""工具注册、发现和受控执行。"""

import asyncio

from .base import Result, Tool, ToolDefinition

DEFAULT_TIMEOUT = 30.0


class Registry:
    """集中登记、发现并安全执行工具。"""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.name()
        if name in self._tools:
            raise ValueError(f"工具已注册: {name}")
        self._order.append(name)
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def count(self) -> int:
        return len(self._tools)

    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=name,
                description=self._tools[name].description(),
                input_schema=self._tools[name].parameters(),
            )
            for name in self._order
        ]

    def read_only_definitions(self) -> list[ToolDefinition]:
        """按注册顺序导出可在 Plan Mode 使用的只读工具。"""

        return [
            ToolDefinition(
                name=name,
                description=self._tools[name].description(),
                input_schema=self._tools[name].parameters(),
            )
            for name in self._order
            if self._tools[name].read_only
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
            return await asyncio.wait_for(tool.execute(args), timeout=timeout)
        except TimeoutError:
            return Result(content=f"工具 {name} 执行超时（{timeout}s）", is_error=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return Result(content=f"工具 {name} 异常: {exc}", is_error=True)
