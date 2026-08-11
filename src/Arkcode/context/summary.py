"""LLM 全量摘要、重试和恢复段拼装。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..llm import (
    Message,
    PromptTooLongError,
    Request,
    StreamError,
    TextDelta,
)
from .constants import (
    ESTIMATE_CHARS_PER_TOKEN,
    MANUAL_SAFETY_MARGIN,
    PTL_DROP_PERCENTAGE,
    PTL_RETRY_LIMIT,
    RECENT_KEEP_MESSAGES,
    RECENT_KEEP_TOKENS,
    SUMMARY_RESERVE,
)
from .prompts import build_summary_prompt, extract_summary
from .recovery import build_recovery_attachment
from .tokens import estimate_tokens, message_chars

if TYPE_CHECKING:
    from .manager import ManageInput


@dataclass(frozen=True)
class CompactionResult:
    """一次真实摘要的结构化结果。"""

    summary: str
    keep: list[Message]
    messages: list[Message]


def pick_recent_tail(msgs: list[Message]) -> list[Message]:
    """从末尾保留同时满足 token 与消息数下界的完整交互。"""

    if not msgs:
        return []
    bytes_total = 0
    count = 0
    start = len(msgs)
    for index in range(len(msgs) - 1, -1, -1):
        bytes_total += message_chars([msgs[index]])
        count += 1
        start = index
        if (
            math.ceil(bytes_total / ESTIMATE_CHARS_PER_TOKEN) >= RECENT_KEEP_TOKENS
            and count >= RECENT_KEEP_MESSAGES
        ):
            break
    if msgs[start].role == "tool":
        result_ids = {result.tool_call_id for result in msgs[start].tool_results}
        for index in range(start - 1, -1, -1):
            call_ids = {call.id for call in msgs[index].tool_calls}
            if msgs[index].role == "assistant" and result_ids & call_ids:
                start = index
                break
    return list(msgs[start:])


def _join_after_summary(
    summary_and_recovery: Message,
    recent: list[Message],
) -> list[Message]:
    """拼接摘要与近期原文，同时维持合法角色序列。"""

    recent = list(recent)
    while recent and recent[0].role == "tool":
        recent.pop(0)
    if not recent:
        return [summary_and_recovery]
    if recent[0].role == "user":
        return [
            summary_and_recovery,
            Message(
                role="assistant",
                content="（已加载上下文摘要与恢复信息。请继续。）",
            ),
            *recent,
        ]
    return [summary_and_recovery, *recent]


def group_by_user_turn(msgs: list[Message]) -> list[list[Message]]:
    """按用户提交边界把消息分成可安全丢弃的交互组。"""

    groups: list[list[Message]] = []
    for message in msgs:
        if message.role == "user" or not groups:
            groups.append([])
        groups[-1].append(message)
    return groups


async def summarize_once(in_: ManageInput, msgs: list[Message]) -> str:
    """发出一次无工具摘要请求并只返回正式摘要。"""

    chunks: list[str] = []
    request = Request(messages=build_summary_prompt(msgs), tools=None)
    async for event in in_.provider.stream(request):
        if isinstance(event, StreamError):
            raise event.error
        if isinstance(event, TextDelta):
            chunks.append(event.text)
    return extract_summary("".join(chunks))


async def ptl_retry(
    in_: ManageInput,
    msgs: list[Message],
    first_err: Exception,
) -> str:
    """通过逐组、再按比例丢弃旧消息重试过长的摘要请求。"""

    groups = group_by_user_turn(msgs)
    latest = first_err
    attempts = 0
    while groups:
        drop = (
            1
            if attempts < PTL_RETRY_LIMIT
            else max(
                1,
                math.ceil(len(groups) * PTL_DROP_PERCENTAGE),
            )
        )
        groups = groups[drop:]
        attempts += 1
        if not groups:
            break
        remaining = [message for group in groups for message in group]
        try:
            return await summarize_once(in_, remaining)
        except PromptTooLongError as error:
            latest = error
    raise latest


async def run_summary(in_: ManageInput) -> CompactionResult:
    """摘要当前历史，返回结构化摘要、保留尾部和最终消息。"""

    old_messages = in_.conv.messages()
    recovery_snapshot = in_.recovery.snapshot()
    summary_prompt = build_summary_prompt(old_messages)
    prompt_tokens = estimate_tokens(0, summary_prompt, 0)
    manual_limit = in_.context_window - SUMMARY_RESERVE - MANUAL_SAFETY_MARGIN
    try:
        if in_.trigger.value == "manual" and prompt_tokens >= manual_limit:
            raise PromptTooLongError("摘要请求估算超过安全阈值")
        summary = await summarize_once(in_, old_messages)
    except PromptTooLongError as error:
        summary = await ptl_retry(in_, old_messages, error)
    recovery = build_recovery_attachment(recovery_snapshot, in_.tool_defs)
    resume_summary = f"## 历史会话摘要\n{summary}\n\n{recovery}"
    combined = Message(
        role="user",
        content=resume_summary,
    )
    messages = _join_after_summary(combined, pick_recent_tail(old_messages))
    return CompactionResult(
        summary=resume_summary,
        keep=list(messages[1:]),
        messages=messages,
    )


async def auto_compact(
    in_: ManageInput,
) -> tuple[CompactionResult, int, int]:
    """执行自动摘要并维护仅属于自动路径的熔断状态。"""

    try:
        result = await run_summary(in_)
    except Exception:
        in_.auto_tracking.record_failure()
        raise
    in_.auto_tracking.record_success()
    return result, in_.estimated_token, estimate_tokens(0, result.messages, 0)


async def force_compact(
    in_: ManageInput,
) -> tuple[CompactionResult, int, int]:
    """绕过阈值与熔断，无条件执行手动或紧急摘要。"""

    result = await run_summary(in_)
    return result, in_.estimated_token, estimate_tokens(0, result.messages, 0)
