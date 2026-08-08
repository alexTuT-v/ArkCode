"""上下文压缩在 Agent 事件流中的生命周期。"""

from dataclasses import dataclass
from enum import Enum


class CompactPhase(Enum):
    """自动与紧急压缩的开始和完成阶段。"""

    BEFORE_AUTO = "before_auto"
    AFTER_AUTO = "after_auto"
    BEFORE_EMERGENCY = "before_emergency"
    AFTER_EMERGENCY = "after_emergency"


@dataclass(frozen=True)
class CompactEvent:
    """供 TUI 呈现的压缩状态。"""

    phase: CompactPhase
    before: int = 0
    after: int = 0
    err: Exception | None = None
