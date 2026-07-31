"""创建或覆盖文本文件。"""

import json
from pathlib import Path
from typing import Any

from .base import Result, Tool


class WriteFileTool(Tool):
    """写入文本文件并自动创建父目录。"""

    read_only = False

    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "创建或覆盖文本文件，父目录不存在时自动创建。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标文件路径"},
                "content": {"type": "string", "description": "要写入的完整内容"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(f"参数 JSON 无效: {exc}", is_error=True)
        if not isinstance(data, dict):
            return Result("参数必须是 JSON 对象", is_error=True)
        path_value = data.get("path")
        content = data.get("content")
        if not isinstance(path_value, str) or not path_value:
            return Result("缺少必填参数 path", is_error=True)
        if not isinstance(content, str):
            return Result("缺少必填参数 content", is_error=True)

        path = Path(path_value)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        except (OSError, UnicodeError) as exc:
            return Result(f"无法写入文件 {path}: {exc}", is_error=True)
        return Result(f"已写入 {path}（{len(content.encode())} 字节）")
