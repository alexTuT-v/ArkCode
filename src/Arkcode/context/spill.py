"""大工具结果进入历史前的确定性落盘与预览替换。"""

import json
from pathlib import Path

from ..llm import ToolCall, ToolResult
from .constants import (
    MESSAGE_AGGREGATE_LIMIT,
    PREVIEW_HEAD_BYTES,
    PREVIEW_HEAD_LINES,
    SINGLE_RESULT_LIMIT,
)
from .state import SessionContext


def spill_single(
    session: SessionContext,
    tool_use_id: str,
    content: str,
) -> None:
    """把完整工具结果幂等写入以调用 ID 命名的文件。"""

    path = Path(session.spill_dir) / tool_use_id
    if path.exists():
        return
    path.write_bytes(content.encode("utf-8"))


def _head_preview(content: str) -> str:
    head = "".join(content.splitlines(keepends=True)[:PREVIEW_HEAD_LINES])
    encoded = head.encode("utf-8")[:PREVIEW_HEAD_BYTES]
    return encoded.decode("utf-8", errors="ignore")


def build_preview(original_bytes: int, head: str, spill_path: str) -> str:
    """构造稳定的工具结果预览替换体。"""

    return "\n".join(
        [
            f"[content offloaded] original size: {original_bytes} bytes",
            f"[saved to] {spill_path}",
            "[head preview]",
            head,
            "完整内容已保存到上述路径，如需查看请用文件读取工具读取该路径，"
            "不要凭头部预览猜测全文",
        ]
    )


def _reads_from_spill(call: ToolCall, session: SessionContext) -> bool:
    """判断工具调用是否在读取 spill 目录内的文件（回读豁免）。"""

    try:
        arguments = json.loads(call.input or "{}")
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(arguments, dict):
        return False
    path = arguments.get("path")
    if not isinstance(path, str) or not path:
        return False
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    return resolved.is_relative_to(Path(session.spill_dir).resolve())


def _preview_result(
    result: ToolResult,
    session: SessionContext,
) -> tuple[ToolResult, bool]:
    """尝试落盘并返回替换后的终态结果；失败时保留原文。"""

    size = len(result.content.encode("utf-8"))
    try:
        spill_single(session, result.tool_call_id, result.content)
    except OSError:
        return result, False
    spill_path = str(Path(session.spill_dir) / result.tool_call_id)
    return (
        ToolResult(
            tool_call_id=result.tool_call_id,
            content=build_preview(size, _head_preview(result.content), spill_path),
            is_error=result.is_error,
        ),
        True,
    )


def prepare_tool_results(
    results: list[ToolResult],
    calls: list[ToolCall],
    session: SessionContext,
) -> list[ToolResult]:
    """在结果进入 Conversation 前完成单条与聚合预算的溢写。"""

    by_id = {call.id: call for call in calls}
    prepared = list(results)

    # 第一阶段：单条超限结果先落盘（回读豁免）。
    for index, result in enumerate(prepared):
        size = len(result.content.encode("utf-8"))
        call = by_id.get(result.tool_call_id)
        if call is not None and _reads_from_spill(call, session):
            continue
        if size <= SINGLE_RESULT_LIMIT:
            continue
        prepared[index], _ = _preview_result(result, session)

    # 第二阶段：批量聚合超限时按大小降序继续溢写最大项。
    sizes = [
        len(result.content.encode("utf-8"))
        if not result.content.startswith("[content offloaded]")
        else 0
        for result in prepared
    ]
    remaining = sum(sizes)
    if remaining <= MESSAGE_AGGREGATE_LIMIT:
        return prepared
    order = sorted(range(len(prepared)), key=sizes.__getitem__, reverse=True)
    for index in order:
        result = prepared[index]
        call = by_id.get(result.tool_call_id)
        if call is not None and _reads_from_spill(call, session):
            continue
        if result.content.startswith("[content offloaded]"):
            continue
        replaced, spilled = _preview_result(result, session)
        if spilled:
            prepared[index] = replaced
            remaining -= sizes[index]
        if remaining <= MESSAGE_AGGREGATE_LIMIT:
            break
    return prepared
