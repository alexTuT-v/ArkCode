"""读取文本文件并添加稳定行号。"""

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from ..base import Result, Tool
from ..utils import truncate

_MAX_CHARS = 256 * 1024


class Params(BaseModel):
    path: str = Field(description="要读取的文件路径")


def _read_limited(path: Path) -> str:
    """最多读取结果上限外加一个字符，用于判断是否需要截断。"""

    with path.open() as handle:
        return handle.read(_MAX_CHARS + 1)


class ReadFileTool(Tool[Params]):
    """读取文本文件。"""

    read_only = True
    params_model = Params

    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return "读取文本文件内容并返回带行号的结果。"

    async def execute(self, params: Params) -> Result:
        path = Path(params.path)
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
