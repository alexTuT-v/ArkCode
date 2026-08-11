"""Agent 单进程会话的上下文管理状态集合。"""

import threading
from dataclasses import dataclass, field

from ..context import (
    CompactCircuitBreaker,
    RecoveryState,
    SessionContext,
)


class ReminderInbox:
    """按 Agent 隔离的请求级提醒队列（FIFO）。"""

    def __init__(self) -> None:
        self._items: list[str] = []
        self._lock = threading.Lock()

    def append(self, text: str) -> None:
        with self._lock:
            self._items.append(text)

    def drain(self) -> list[str]:
        with self._lock:
            items = self._items
            self._items = []
            return items

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


@dataclass
class SessionRuntime:
    """跨用户轮次保留的压缩、恢复与 usage 锚点。"""

    recovery: RecoveryState
    auto_tracking: CompactCircuitBreaker
    session: SessionContext
    context_window: int = 200000
    usage_anchor: int = 0
    anchor_msg_len: int = 0
    inbox: ReminderInbox = field(default_factory=ReminderInbox)

    def reset_for_new_session(self, session: SessionContext) -> None:
        self.recovery = RecoveryState()
        self.auto_tracking = CompactCircuitBreaker()
        self.session = session
        self.usage_anchor = 0
        self.anchor_msg_len = 0
        self.inbox = ReminderInbox()
