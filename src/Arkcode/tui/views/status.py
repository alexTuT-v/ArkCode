"""状态栏与 MCP 启动汇总渲染。"""

from rich.table import Table
from rich.text import Text

from ...llm import Provider
from ...mcp import McpStatus
from ...permissions import Mode


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
