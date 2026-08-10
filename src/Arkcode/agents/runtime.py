"""Agent 单进程会话的上下文管理状态集合。"""

from dataclasses import dataclass

from ..context import (
    CompactCircuitBreaker,
    RecoveryState,
    SessionContext,
)


@dataclass
class SessionRuntime:
    """跨用户轮次保留的压缩、恢复与 usage 锚点。"""

    recovery: RecoveryState
    auto_tracking: CompactCircuitBreaker
    session: SessionContext
    context_window: int = 200000
    usage_anchor: int = 0
    anchor_msg_len: int = 0

    def reset_for_new_session(self, session: SessionContext) -> None:
        self.recovery = RecoveryState()
        self.auto_tracking = CompactCircuitBreaker()
        self.session = session
        self.usage_anchor = 0
        self.anchor_msg_len = 0
