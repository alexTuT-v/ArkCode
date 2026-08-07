"""TUI 中可复用的 Rich 渲染块。"""

from collections.abc import Sequence
from typing import Protocol

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from ..agent import ApprovalRequest
from ..llm import Provider
from ..mcp import McpStatus
from ..permission import Mode


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


def mcp_status_line(status: McpStatus) -> Text | None:
    """渲染一次性的 MCP 启动汇总；零配置时不占用界面。"""

    if status.configured_servers == 0:
        return None
    line = Text(
        f"MCP {status.connected_servers}/{status.configured_servers} "
        f"servers connected · {status.registered_tools} tools registered",
        style="dim",
    )
    if status.failed_servers > 0:
        line.append(f" · {status.failed_servers} failed", style="yellow")
    return line


def _compact_tokens(value: int) -> str:
    if value < 1000:
        return str(value)
    compact = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
    return f"{compact}k"


def status_bar(
    provider: Provider,
    mode: Mode = Mode.DEFAULT,
    usage_in: int = 0,
    usage_out: int = 0,
    usage_cache_read: int = 0,
    usage_cache_creation: int = 0,
) -> Table:
    """渲染当前权限模式、模型与累计 token 用量。"""

    table = Table.grid(expand=True)
    table.add_column(justify="left", ratio=1)
    table.add_column(justify="right")
    labels = {
        Mode.DEFAULT: ("DEFAULT", "green"),
        Mode.ACCEPT_EDITS: ("ACCEPT EDITS", "cyan"),
        Mode.PLAN: ("PLAN", "yellow"),
        Mode.BYPASS: ("BYPASS", "bold red"),
    }
    label, style = labels[mode]
    usage = (
        f"↑{_compact_tokens(usage_in)} ↓{_compact_tokens(usage_out)} tok"
        f" · cache 读 {_compact_tokens(usage_cache_read)}"
        f" / 写 {_compact_tokens(usage_cache_creation)}"
    )
    table.add_row(Text(label, style=style), f"{provider.model}  {usage}")
    return table


def approval_block(request: ApprovalRequest, cursor: int = 0) -> Text:
    """渲染人在回路的三选一批准菜单。"""

    choices = (
        "1. 允许本次",
        "2. 永久允许（写入本地配置）",
        "3. 拒绝本次",
    )
    block = Text()
    block.append(f"● {request.name}\n", style="bold cyan")
    block.append(f"  {request.args}\n", style="bold")
    block.append(f"  {request.reason}\n", style="dim")
    block.append("是否继续?\n")
    for index, choice in enumerate(choices):
        selected = index == cursor
        block.append(
            ("> " if selected else "  ") + choice + "\n",
            style="reverse bold" if selected else "",
        )
    block.append("↑↓ 选择 · 回车确认 · Esc 取消", style="dim")
    return block


def tool_line(name: str, args: str) -> Text:
    """渲染 Claude Code 风格的工具调用行。"""

    text = Text("● ", style="bold cyan")
    text.append(f"{name}({args})", style="bold")
    return text


def tool_result_summary(result: str, is_error: bool) -> RenderableType:
    """渲染至多八行的缩进工具结果摘要。"""

    lines = result.splitlines()
    truncated = len(lines) > 8 or len(result) > 2000
    summary = "\n".join(lines[:8])
    if len(summary) > 2000:
        summary = summary[:2000]
    if truncated:
        summary = summary.rstrip() + "\n[truncated]"
    return Padding(
        Text("⎿ " + summary, style="red" if is_error else "dim"),
        (0, 0, 0, 2),
    )


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
