"""流式呈现状态。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolDisplay:
    """动态区当前正在执行的工具。"""

    name: str
    args: str


@dataclass
class StreamingState:
    """一轮流式回复的纯展示状态。"""

    reply: str = ""
    thinking: str = ""
    tools: list[ToolDisplay] = field(default_factory=list)
    iteration: int = 0
