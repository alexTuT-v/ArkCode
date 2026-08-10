"""创建或覆盖文本文件。"""

from pathlib import Path

from pydantic import BaseModel, Field

from ..base import Result, Tool


class Params(BaseModel):
    path: str = Field(description="目标文件路径")
    content: str = Field(description="要写入的完整内容")


class WriteFileTool(Tool[Params]):
    """写入文本文件并自动创建父目录。"""

    read_only = False
    params_model = Params

    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "创建或覆盖文本文件，父目录不存在时自动创建。"

    async def execute(self, params: Params) -> Result:
        path = Path(params.path)
        content = params.content
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        except (OSError, UnicodeError) as exc:
            return Result(f"无法写入文件 {path}: {exc}", is_error=True)
        return Result(f"已写入 {path}（{len(content.encode())} 字节）")
