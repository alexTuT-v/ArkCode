"""上下文管理的单一编排入口：只计算结果，不修改 Conversation。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from ..conversations import Conversation
from ..llm import Provider, ToolDefinition
from .constants import AUTO_SAFETY_MARGIN, SUMMARY_RESERVE
from .state import (
    CompactCircuitBreaker,
    RecoveryState,
    SessionContext,
)
from .summary import CompactionResult
from .tokens import estimate_tokens

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
    recovery: RecoveryState
    auto_tracking: CompactCircuitBreaker
    session: SessionContext
    usage_anchor: int
    anchor_msg_len: int
    estimated_token: int
    trigger: TriggerKind


@dataclass(frozen=True)
class ManageOutput:
    """压缩入口前后的估算 token 数与可选的结构化压缩结果。"""

    before_tokens: int
    after_tokens: int
    compaction: CompactionResult | None = None

    @property
    def compacted(self) -> bool:
        return self.compaction is not None


def build_manage_input(
    *,
    conv: Conversation,
    provider: Provider,
    model: str,
    context_window: int,
    tool_defs: list[ToolDefinition],
    recovery: RecoveryState,
    auto_tracking: CompactCircuitBreaker,
    session: SessionContext,
    usage_anchor: int,
    anchor_msg_len: int,
    estimated_token: int,
    trigger: TriggerKind,
) -> ManageInput:
    """按会话运行状态构造单次上下文管理的输入。"""

    return ManageInput(
        conv=conv,
        provider=provider,
        model=model,
        context_window=context_window,
        tool_defs=tool_defs,
        recovery=recovery,
        auto_tracking=auto_tracking,
        session=session,
        usage_anchor=usage_anchor,
        anchor_msg_len=anchor_msg_len,
        estimated_token=estimated_token,
        trigger=trigger,
    )


async def manage_context(in_: ManageInput) -> ManageOutput:
    """按触发来源计算摘要结果；任何情况下都不修改会话历史。"""

    from .summary import auto_compact, force_compact

    if in_.trigger is TriggerKind.MANUAL:
        result, before, after = await force_compact(in_)
        return ManageOutput(before, after, compaction=result)

    if in_.trigger is TriggerKind.EMERGENCY:
        result, before, after = await force_compact(in_)
        return ManageOutput(before, after, compaction=result)

    original_messages = in_.conv.messages()
    estimated = estimate_tokens(
        in_.usage_anchor,
        original_messages,
        in_.anchor_msg_len,
    )
    if in_.context_window <= SUMMARY_RESERVE + AUTO_SAFETY_MARGIN:
        logger.warning("上下文窗口不足以安全执行自动摘要")
        return ManageOutput(in_.estimated_token, estimated)
    threshold = in_.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
    if estimated < threshold or in_.auto_tracking.tripped():
        return ManageOutput(in_.estimated_token, estimated)
    result, before, after = await auto_compact(in_)
    return ManageOutput(before, after, compaction=result)
