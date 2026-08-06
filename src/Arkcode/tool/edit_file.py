"""通过唯一原文匹配精确编辑文件。"""

import json
from pathlib import Path
from typing import Any

from .base import Result, Tool


class EditFileTool(Tool):
    """只在原文片段唯一出现时替换文件内容。"""

    read_only = False

    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return (
            "用新文本替换文件中唯一匹配的原文片段。"
            "编辑前请先用 read_file 读取目标文件，并确认 old_string 唯一。"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要编辑的文件路径"},
                "old_string": {
                    "type": "string",
                    "description": "必须在文件中唯一出现的原文",
                },
                "new_string": {"type": "string", "description": "替换后的文本"},
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(f"参数 JSON 无效: {exc}", is_error=True)
        if not isinstance(data, dict):
            return Result("参数必须是 JSON 对象", is_error=True)
        path_value = data.get("path")
        old_string = data.get("old_string")
        new_string = data.get("new_string")
        if not isinstance(path_value, str) or not path_value:
            return Result("缺少必填参数 path", is_error=True)
        if not isinstance(old_string, str) or not old_string:
            return Result("缺少必填参数 old_string", is_error=True)
        if not isinstance(new_string, str):
            return Result("缺少必填参数 new_string", is_error=True)

        path = Path(path_value)
        try:
            content = path.read_text()
        except (OSError, UnicodeError) as exc:
            return Result(f"无法读取文件 {path}: {exc}", is_error=True)
        count = content.count(old_string)
        if count == 0:
            return Result("未找到匹配的内容", is_error=True)
        if count > 1:
            return Result(
                f"匹配到 {count} 处，old_string 不唯一，请提供更长上下文使其唯一",
                is_error=True,
            )
        try:
            path.write_text(content.replace(old_string, new_string, 1))
        except (OSError, UnicodeError) as exc:
            return Result(f"无法写入文件 {path}: {exc}", is_error=True)
        return Result(f"已更新 {path}")
