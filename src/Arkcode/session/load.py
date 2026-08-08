"""从 JSONL 恢复协议无关的会话消息。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..llm import Message, ToolCall, ToolResult


def _message(value: dict[str, Any]) -> Message | None:
    role = value.get("role")
    if role not in {"user", "assistant", "tool"}:
        return None
    calls = [
        ToolCall(
            id=str(item.get("id", "")),
            name=str(item.get("name", "")),
            input=str(item.get("input", "")),
        )
        for item in value.get("tool_calls") or []
        if isinstance(item, dict)
    ]
    results = [
        ToolResult(
            tool_call_id=str(item.get("tool_call_id", "")),
            content=str(item.get("content", "")),
            is_error=bool(item.get("is_error", False)),
        )
        for item in value.get("tool_results") or []
        if isinstance(item, dict)
    ]
    return Message(
        role=role,
        content=str(value.get("content", "")),
        tool_calls=calls,
        tool_results=results,
        thinking=str(value.get("thinking", "")),
        thinking_signature=str(value.get("thinking_signature", "")),
    )


def _truncate_orphaned_tool_calls(messages: list[Message]) -> list[Message]:
    if messages and messages[-1].role == "assistant" and messages[-1].tool_calls:
        return messages[:-1]
    return messages


def load_session(session_dir: str) -> list[Message]:
    """加载最后一次压缩后的有效消息，并跳过损坏行。"""

    path = Path(session_dir) / "conversation.jsonl"
    values: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            try:
                value = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            if value.get("type") == "compact":
                values.clear()
            else:
                values.append(value)
    messages = [message for value in values if (message := _message(value)) is not None]
    return _truncate_orphaned_tool_calls(messages)


def last_message_timestamp(session_dir: str) -> int | None:
    """返回最后一次压缩边界之后的最后一条有效消息时间。"""

    path = Path(session_dir) / "conversation.jsonl"
    latest: int | None = None
    with path.open(encoding="utf-8") as source:
        for line in source:
            try:
                value = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            if value.get("type") == "compact":
                latest = None
                continue
            if value.get("role") in {"user", "assistant", "tool"}:
                timestamp = value.get("ts")
                if isinstance(timestamp, int):
                    latest = timestamp
    return latest
