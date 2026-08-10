"""摘要后用于恢复精确信息的稳定文本。"""

import json

from ..llm import ToolDefinition
from .constants import (
    ESTIMATE_CHARS_PER_TOKEN,
    RECOVERY_FILE_LIMIT,
    RECOVERY_TOKENS_PER_FILE,
)
from .state import FileReadRecord

BOUNDARY_NOTICE = """\
需要文件原文、错误原文或用户原话时，请使用文件读取工具重新读取对应路径，
不要依据摘要内容做猜测。"""


def render_file_block(record: FileReadRecord) -> str:
    """渲染文件路径、读取时间和有上限的头部内容。"""

    char_limit = int(RECOVERY_TOKENS_PER_FILE * ESTIMATE_CHARS_PER_TOKEN)
    fragment = record.content
    if len(fragment) > char_limit:
        fragment = f"{fragment[:char_limit]}\n(content truncated)"
    return f"### {record.path}\n[read at] {record.timestamp.isoformat()}\n{fragment}\n"


def render_tools_block(definitions: list[ToolDefinition]) -> str:
    """逐项渲染将与下一次请求共用的工具定义。"""

    lines: list[str] = []
    for definition in definitions:
        schema = json.dumps(
            definition.input_schema,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        lines.extend(
            [
                f"- {definition.name}: {definition.description}",
                f"  schema: {schema}",
            ]
        )
    return "\n".join(lines) if lines else "(无)"


def build_recovery_attachment(
    snapshot: list[FileReadRecord],
    tool_defs: list[ToolDefinition],
) -> str:
    """从单次状态快照构造文件、工具和边界提示三段。"""

    files = "".join(
        render_file_block(record) for record in snapshot[:RECOVERY_FILE_LIMIT]
    )
    if not files:
        files = "(无)\n"
    return (
        f"## 最近读过的文件\n{files}\n"
        f"## 当前可用工具\n{render_tools_block(tool_defs)}\n\n"
        f"## 边界提示\n{BOUNDARY_NOTICE}"
    )
