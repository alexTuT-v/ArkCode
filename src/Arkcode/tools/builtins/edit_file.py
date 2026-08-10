"""通过唯一原文匹配精确编辑文件。"""

from pathlib import Path

from pydantic import BaseModel, Field

from ..base import Result, Tool


class Params(BaseModel):
    path: str = Field(description="要编辑的文件路径")
    old_string: str = Field(description="必须在文件中唯一出现的原文")
    new_string: str = Field(description="替换后的文本")


class EditFileTool(Tool[Params]):
    """只在原文片段唯一出现时替换文件内容。"""

    read_only = False
    params_model = Params

    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return (
            "用新文本替换文件中唯一匹配的原文片段。"
            "编辑前请先用 read_file 读取目标文件，并确认 old_string 唯一。"
        )

    async def execute(self, params: Params) -> Result:
        path = Path(params.path)
        old_string = params.old_string
        new_string = params.new_string
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
