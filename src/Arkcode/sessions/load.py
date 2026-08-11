"""从格式 v2 JSONL 流式恢复会话消息。"""

from __future__ import annotations

import copy
from pathlib import Path

from ..llm import Message, ToolResult
from .record import CompactBoundary, SessionRecord, decode_record

RESUME_SUMMARY_PREFIX = "（已压缩的历史摘要）\n\n"


def _summary_message(boundary: CompactBoundary) -> Message:
    return Message(
        role="user",
        content=RESUME_SUMMARY_PREFIX + boundary.summary,
    )


def _repair_pairing(messages: list[Message]) -> list[Message]:
    """补齐被中断的工具调用，并丢弃从未被调用的孤立结果。"""

    issued: set[str] = set()
    completed: set[str] = set()
    for message in messages:
        issued.update(call.id for call in message.tool_calls)
        completed.update(
            result.tool_call_id
            for result in message.tool_results
            if result.tool_call_id in issued
        )

    rebuilt: list[Message] = []
    for message in messages:
        if message.role == "assistant":
            rebuilt.append(message)
            interrupted = [
                ToolResult(call_id, "工具调用被中断", is_error=True)
                for call_id in {call.id for call in message.tool_calls}
                if call_id not in completed
            ]
            if interrupted:
                rebuilt.append(
                    Message(
                        role="tool",
                        tool_results=interrupted,
                    )
                )
        elif message.role == "tool":
            kept = [
                result
                for result in message.tool_results
                if result.tool_call_id in issued
            ]
            if kept:
                rebuilt.append(
                    Message(role="tool", tool_results=kept)
                )
        else:
            rebuilt.append(message)
    return rebuilt


def load_session(session_dir: str | Path) -> list[Message]:
    """流式读取 JSONL，从最后一个有效压缩边界投影并修复工具配对。"""

    path = Path(session_dir) / "conversation.jsonl"
    if not path.is_file():
        return []
    active: list[Message] = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            record: SessionRecord | None = decode_record(line)
            if isinstance(record, Message):
                active.append(record)
            elif isinstance(record, CompactBoundary):
                active = [
                    _summary_message(record),
                    *copy.deepcopy(record.keep),
                ]
    return _repair_pairing(active)


def last_message_timestamp(session_dir: str | Path) -> int | None:
    """返回最后一次压缩边界之后的最后一条有效消息时间。"""

    path = Path(session_dir) / "conversation.jsonl"
    latest: int | None = None
    with path.open(encoding="utf-8") as source:
        for line in source:
            record: SessionRecord | None = decode_record(line)
            if isinstance(record, Message):
                latest = record_ts(line)
            elif isinstance(record, CompactBoundary):
                latest = record.timestamp
    return latest


def record_ts(line: str) -> int | None:
    """读取单条记录中的 ts 字段（供时间戳查询使用）。"""

    import json

    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    ts = value.get("ts")
    return ts if isinstance(ts, int) else None
