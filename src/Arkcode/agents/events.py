"""Agent 对外输出的事件模型与停止通知。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum

from ..permissions import Outcome

NOTICE_MAX_ITER = "（已达最大迭代轮数 25，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED = "（已取消。）"
NOTICE_EMPTY_FINAL = "（模型未返回文本。）"


class Phase(Enum):
    """工具调用在界面上的生命周期阶段。"""

    START = "start"
    END = "end"


@dataclass(frozen=True)
class Usage:
    """一次模型请求的输入与输出 token 用量。"""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    cache_write: int = 0


@dataclass(frozen=True)
class ApprovalRequest:
    """等待界面回传单次权限选择。"""

    name: str
    args: str
    reason: str
    respond: asyncio.Future[Outcome]


@dataclass(frozen=True)
class ToolEvent:
    """供界面展示的一次工具开始或结束事件。"""

    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass(frozen=True)
class AgentEvent:
    """Agent 对外输出的统一事件。"""

    text: str = ""
    thinking: str = ""
    tool: ToolEvent | None = None
    usage: Usage | None = None
    iter: int = 0
    notice: str = ""
    done: bool = False
    err: Exception | None = None
    approval: ApprovalRequest | None = None
    compact: CompactEvent | None = None


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
