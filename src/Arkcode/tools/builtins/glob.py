"""按 glob 模式查找文件。"""

import asyncio

from pydantic import BaseModel, Field

from ..base import Result, Tool
from ..workspace import Access, PathPermissionError, resolve_path


class Params(BaseModel):
    pattern: str = Field(description="glob 模式")
    path: str | None = Field(default=None, description="搜索根目录，默认当前目录")


class GlobTool(Tool[Params]):
    """递归查找匹配 glob 模式的文件。"""

    read_only = True
    params_model = Params

    def name(self) -> str:
        return "glob"

    def description(self) -> str:
        return "按 glob 模式查找文件，最多返回 100 条。"

    async def execute(self, params: Params) -> Result:
        pattern = params.pattern
        root_value = params.path or "."

        try:
            root = resolve_path(root_value, Access.READ)
        except PathPermissionError as exc:
            return Result(str(exc), is_error=True)
        if not root.is_dir():
            return Result(f"搜索目录不存在: {root}", is_error=True)
        matches: list[str] = []
        truncated = False
        try:
            for index, path in enumerate(root.glob(pattern), 1):
                if path.is_file():
                    try:
                        real = resolve_path(str(path), Access.READ)
                    except PathPermissionError:
                        continue
                    if real != path.resolve():
                        path = real
                    if len(matches) == 100:
                        truncated = True
                        break
                    matches.append(str(path))
                if index % 100 == 0:
                    await asyncio.sleep(0)
        except (OSError, ValueError) as exc:
            return Result(f"glob 搜索失败: {exc}", is_error=True)
        if not matches:
            return Result("无匹配")
        content = "\n".join(sorted(matches))
        if truncated:
            content += "\n[truncated]"
        return Result(content)
