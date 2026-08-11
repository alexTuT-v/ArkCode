"""用户、错误、Markdown 与流式区块渲染。"""

from collections.abc import Sequence
from typing import Protocol

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.text import Text

from ...agents import CompactEvent, CompactPhase


def format_compact_notice(event: CompactEvent) -> str:
    if event.phase is CompactPhase.BEFORE_AUTO:
        return "正在压缩上下文..."
    if event.phase is CompactPhase.BEFORE_EMERGENCY:
        return "上下文撞墙，自动压缩中..."
    if event.err is not None:
        return f"压缩失败：{event.err}"
    return f"已压缩，token 从 {event.before} 降至 {event.after}"


class RunningTool(Protocol):
    """动态区渲染工具所需的最小字段。"""

    @property
    def name(self) -> str: ...

    @property
    def args(self) -> str: ...


def user_block(message: str) -> Text:
    """渲染一条已提交的用户消息。"""

    return Text("● " + message, style="bold")


def render_markdown(reply: str, elapsed: float) -> RenderableType:
    """渲染完成的 Markdown 回复及总耗时。"""

    return Group(
        Text("●", style="bold cyan"),
        Markdown(reply),
        Text(f"Completed in {elapsed:.1f}s", style="dim"),
    )


def error_block(message: str, elapsed: float) -> Text:
    """渲染可区分且带耗时的错误消息。"""

    return Text(f"● {message}\nFailed after {elapsed:.1f}s", style="bold red")


def streaming_block(
    reply: str,
    elapsed: int,
    tools: Sequence[RunningTool] = (),
    iteration: int = 0,
    thinking: str = "",
) -> Text:
    """渲染当前文本、多个并发工具或迭代进度。"""

    if tools:
        return Text(
            "\n".join(
                f"● {tool.name}({tool.args}) Running… ({elapsed}s)" for tool in tools
            )
        )
    body = Text()
    if thinking:
        body.append(f"◌ {thinking}\n", style="dim")
    if reply:
        body.append(f"● {reply}\n")
    progress = f"{elapsed}s"
    if iteration:
        progress += f" · 第 {iteration} 轮"
    body.append(f"Imagining… ({progress})")
    return body
