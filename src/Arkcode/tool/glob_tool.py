"""按 glob 模式查找文件。"""

import asyncio
import json
from pathlib import Path
from typing import Any

from .base import Result, Tool


class GlobTool(Tool):
    """递归查找匹配 glob 模式的文件。"""

    read_only = True

    def name(self) -> str:
        return "glob"

    def description(self) -> str:
        return "按 glob 模式查找文件，最多返回 100 条。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "glob 模式"},
                "path": {"type": "string", "description": "搜索根目录，默认当前目录"},
            },
            "required": ["pattern"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(f"参数 JSON 无效: {exc}", is_error=True)
        if not isinstance(data, dict):
            return Result("参数必须是 JSON 对象", is_error=True)
        pattern = data.get("pattern")
        root_value = data.get("path") or "."
        if not isinstance(pattern, str) or not pattern:
            return Result("缺少必填参数 pattern", is_error=True)
        if not isinstance(root_value, str):
            return Result("参数 path 必须是字符串", is_error=True)

        root = Path(root_value)
        if not root.is_dir():
            return Result(f"搜索目录不存在: {root}", is_error=True)
        matches: list[str] = []
        truncated = False
        try:
            for index, path in enumerate(root.glob(pattern), 1):
                if path.is_file():
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
