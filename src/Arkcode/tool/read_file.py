"""读取文本文件并添加稳定行号。"""

import asyncio
import json
from pathlib import Path
from typing import Any

from .base import Result, Tool
from .utils import truncate

_MAX_CHARS = 256 * 1024


def _read_limited(path: Path) -> str:
    """最多读取结果上限外加一个字符，用于判断是否需要截断。"""

    with path.open() as handle:
        return handle.read(_MAX_CHARS + 1)


class ReadFileTool(Tool):
    """读取文本文件。"""

    read_only = True

    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return "读取文本文件内容并返回带行号的结果。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要读取的文件路径"}
            },
            "required": ["path"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(f"参数 JSON 无效: {exc}", is_error=True)
        path_value = data.get("path") if isinstance(data, dict) else None
        if not isinstance(path_value, str) or not path_value:
            return Result("缺少必填参数 path", is_error=True)

        path = Path(path_value)
        if not path.exists():
            return Result(f"文件不存在: {path}", is_error=True)
        if path.is_dir():
            return Result(f"路径是目录而不是文件: {path}", is_error=True)
        try:
            text = await asyncio.to_thread(_read_limited, path)
        except (OSError, UnicodeError) as exc:
            return Result(f"无法读取文件 {path}: {exc}", is_error=True)

        numbered = "\n".join(
            f"{number:6d}\t{line}" for number, line in enumerate(text.splitlines(), 1)
        )
        return Result(truncate(numbered, max_lines=2000, max_chars=_MAX_CHARS))
