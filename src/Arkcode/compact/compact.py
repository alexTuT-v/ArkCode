"""两层上下文管理的单一编排入口。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from ..conversation import Conversation
from ..llm import Provider, ToolDefinition
from .const import AUTO_SAFETY_MARGIN, SUMMARY_RESERVE
from .layer1 import offload_and_snip
from .state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)
from .token import estimate_tokens, message_chars

logger = logging.getLogger(__name__)


class TriggerKind(Enum):
    """上下文压缩的触发来源。"""

    AUTO = "auto"
    MANUAL = "manual"
    EMERGENCY = "emergency"


@dataclass
class ManageInput:
    """单次上下文管理所需的稳定输入与会话状态。"""

    conv: Conversation
    provider: Provider
    model: str
    context_window: int
    tool_defs: list[ToolDefinition]
    replacement: ContentReplacementState
    recovery: RecoveryState
    auto_tracking: CompactCircuitBreaker
    session: SessionContext
    usage_anchor: int
    anchor_msg_len: int
    estimated_token: int
    trigger: TriggerKind


@dataclass(frozen=True)
class ManageOutput:
    """压缩入口前后的估算 token 数。"""

    before_tokens: int
    after_tokens: int
    compacted: bool = False


async def manage_context(in_: ManageInput) -> ManageOutput:
    """按触发来源执行 Layer 1、阈值判断和 Layer 2。"""

    from .layer2 import auto_compact, force_compact

    if in_.trigger is TriggerKind.MANUAL:
        messages, before, after = await force_compact(in_)
        in_.conv.replace_history(messages)
        logger.info(
            "context compact trigger=%s before=%d after=%d replacements=%d",
            in_.trigger.value,
            before,
            after,
            in_.replacement.replacement_count(),
        )
        return ManageOutput(before, after, compacted=True)

    if in_.trigger is TriggerKind.EMERGENCY:
        layer1_messages = offload_and_snip(
            in_.conv.messages(),
            in_.replacement,
            in_.session,
        )
        in_.conv.replace_history(layer1_messages)
        messages, before, after = await force_compact(in_)
        in_.conv.replace_history(messages)
        logger.info(
            "context compact trigger=%s before=%d after=%d replacements=%d",
            in_.trigger.value,
            before,
            after,
            in_.replacement.replacement_count(),
        )
        return ManageOutput(before, after, compacted=True)

    original_messages = in_.conv.messages()
    layer1_messages = offload_and_snip(
        original_messages,
        in_.replacement,
        in_.session,
    )
    in_.conv.replace_history(layer1_messages)
    if message_chars(layer1_messages) < message_chars(original_messages):
        estimated = estimate_tokens(0, layer1_messages, 0)
    else:
        estimated = estimate_tokens(
            in_.usage_anchor,
            layer1_messages,
            in_.anchor_msg_len,
        )
    if in_.context_window <= SUMMARY_RESERVE + AUTO_SAFETY_MARGIN:
        logger.warning("上下文窗口不足以安全执行自动摘要")
        return ManageOutput(in_.estimated_token, estimated)
    threshold = in_.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
    if estimated < threshold or in_.auto_tracking.tripped():
        return ManageOutput(in_.estimated_token, estimated)
    messages, before, after = await auto_compact(in_)
    in_.conv.replace_history(messages)
    logger.info(
        "context compact trigger=%s before=%d after=%d replacements=%d",
        in_.trigger.value,
        before,
        after,
        in_.replacement.replacement_count(),
    )
    return ManageOutput(before, after, compacted=True)
