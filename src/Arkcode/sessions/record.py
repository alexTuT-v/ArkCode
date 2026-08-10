"""格式 v2 会话记录的协议无关编解码。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Literal

from ..llm import ROLE_ASSISTANT, ROLE_TOOL, ROLE_USER, Message, ToolCall, ToolResult

ROLES = {"user", "assistant", "tool"}


@dataclass(frozen=True)
class CompactBoundary:
    """一次真实摘要产生的自包含恢复边界。"""

    summary: str
    keep: list[Message]
    timestamp: int


type SessionRecord = Message | CompactBoundary


def _arguments(raw: str) -> dict[str, Any]:
    """把内存中的参数字符串转换为磁盘上的 JSON object。"""

    value = json.loads(raw or "{}")
    if not isinstance(value, dict):
        raise ValueError("工具参数必须是 JSON object")
    return value


def _message_value(
    message: Message,
    *,
    timestamp: int | None,
    with_ts: bool,
) -> dict[str, Any]:
    """把消息转成紧凑字典；空字段与默认值一律省略。"""

    value: dict[str, Any] = {"role": message.role}
    if with_ts:
        value["ts"] = int(time.time()) if timestamp is None else timestamp
    if message.content:
        value["content"] = message.content
    if message.tool_calls:
        value["tool_calls"] = [
            {
                "id": call.id,
                "name": call.name,
                "arguments": _arguments(call.input),
            }
            for call in message.tool_calls
        ]
    if message.tool_results:
        results: list[dict[str, Any]] = []
        for result in message.tool_results:
            item: dict[str, Any] = {
                "tool_call_id": result.tool_call_id,
                "content": result.content,
            }
            if result.is_error:
                item["is_error"] = True
            results.append(item)
        value["tool_results"] = results
    return value


def _encode(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def encode_message(
    message: Message,
    *,
    timestamp: int | None = None,
) -> bytes:
    """把普通消息编码为单行 JSONL。"""

    return _encode(_message_value(message, timestamp=timestamp, with_ts=True))


def encode_boundary(boundary: CompactBoundary) -> bytes:
    """把压缩边界编码为单行 JSONL。"""

    value: dict[str, Any] = {
        "type": "compact_boundary",
        "role": "system",
        "content": {
            "summary": boundary.summary,
            "keep": [
                _message_value(message, timestamp=None, with_ts=False)
                for message in boundary.keep
            ],
        },
        "ts": boundary.timestamp,
    }
    return _encode(value)


def _decode_calls(items: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for item in items or []:
        if not isinstance(item, dict):
            raise ValueError("tool_calls 必须是 object 数组")
        arguments = item.get("arguments")
        if not isinstance(arguments, dict):
            raise ValueError("工具参数必须是 JSON object")
        calls.append(
            ToolCall(
                id=str(item.get("id", "")),
                name=str(item.get("name", "")),
                input=json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
            )
        )
    return calls


def _decode_results(items: Any) -> list[ToolResult]:
    results: list[ToolResult] = []
    for item in items or []:
        if not isinstance(item, dict):
            raise ValueError("tool_results 必须是 object 数组")
        results.append(
            ToolResult(
                tool_call_id=str(item.get("tool_call_id", "")),
                content=str(item.get("content", "")),
                is_error=bool(item.get("is_error", False)),
            )
        )
    return results


def _decode_message(value: dict[str, Any]) -> Message:
    role = value.get("role")
    if role not in ROLES:
        raise ValueError(f"未知角色: {role}")
    typed_role: Literal["user", "assistant", "tool"]
    if role == ROLE_USER:
        typed_role = ROLE_USER
    elif role == ROLE_ASSISTANT:
        typed_role = ROLE_ASSISTANT
    else:
        typed_role = ROLE_TOOL
    return Message(
        role=typed_role,
        content=str(value.get("content", "")),
        tool_calls=_decode_calls(value.get("tool_calls")),
        tool_results=_decode_results(value.get("tool_results")),
    )


def _decode_boundary(value: dict[str, Any]) -> CompactBoundary:
    content = value["content"]
    if not isinstance(content, dict):
        raise ValueError("boundary content 必须是 object")
    summary = content.get("summary")
    if not isinstance(summary, str):
        raise ValueError("boundary summary 必须是字符串")
    raw_keep = content.get("keep")
    if not isinstance(raw_keep, list):
        raise ValueError("boundary keep 必须是数组")
    keep = [_decode_message(item) for item in raw_keep]
    timestamp = value.get("ts")
    if not isinstance(timestamp, int):
        raise ValueError("boundary ts 必须是整数")
    return CompactBoundary(summary=summary, keep=keep, timestamp=timestamp)


def decode_record(line: str | bytes) -> SessionRecord | None:
    """严格解析一行；任何损坏、未知或格式错误都返回 None。"""

    try:
        value = json.loads(line)
        if not isinstance(value, dict):
            return None
        if value.get("type") == "compact_boundary":
            return _decode_boundary(value)
        if value.get("type") is not None:
            return None
        role = value.get("role")
        if role not in ROLES:
            return None
        if not isinstance(value.get("ts"), int):
            return None
        return _decode_message(value)
    except (json.JSONDecodeError, TypeError, ValueError, KeyError):
        return None
