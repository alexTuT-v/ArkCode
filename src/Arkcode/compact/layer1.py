"""大工具结果的确定性落盘与预览替换。"""

import copy
from pathlib import Path

from ..llm import Message, ToolResult
from .const import (
    MESSAGE_AGGREGATE_LIMIT,
    PREVIEW_HEAD_BYTES,
    PREVIEW_HEAD_LINES,
    SINGLE_RESULT_LIMIT,
)
from .state import ContentReplacementState, SessionContext


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


def offload_and_snip(
    msgs: list[Message],
    state: ContentReplacementState,
    session: SessionContext,
) -> list[Message]:
    """按单条和单消息聚合预算落盘结果，不修改输入消息。"""

    out = copy.deepcopy(msgs)
    for message in out:
        if message.role != "tool":
            continue
        original_results = list(message.tool_results)
        sizes = [len(result.content.encode("utf-8")) for result in original_results]
        remaining = sum(
            size
            for result, size in zip(original_results, sizes, strict=True)
            if state._lookup(result.tool_call_id)[1] is None
        )
        order = sorted(
            range(len(original_results)),
            key=sizes.__getitem__,
            reverse=True,
        )
        rewritten: list[ToolResult | None] = [None] * len(original_results)

        for index in order:
            result = original_results[index]
            size = sizes[index]
            seen, replacement = state._lookup(result.tool_call_id)
            if seen:
                content = replacement if replacement is not None else result.content
            else:
                should_spill = (
                    size > SINGLE_RESULT_LIMIT or remaining > MESSAGE_AGGREGATE_LIMIT
                )

                def decide() -> tuple[str, str]:
                    if not should_spill:
                        return "kept", ""
                    try:
                        spill_single(session, result.tool_call_id, result.content)
                    except OSError:
                        return "skip", ""
                    spill_path = str(Path(session.spill_dir) / result.tool_call_id)
                    return (
                        "replaced",
                        build_preview(size, _head_preview(result.content), spill_path),
                    )

                content = state.decide_once(result.tool_call_id, result.content, decide)
                if should_spill and content != result.content:
                    remaining -= size
            rewritten[index] = ToolResult(
                tool_call_id=result.tool_call_id,
                content=content,
                is_error=result.is_error,
            )
        message.tool_results[:] = [item for item in rewritten if item is not None]
    return out
