"""/mcp 命令：显示 MCP server 连接状态与工具数量。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_mcp(context: CommandContext) -> None:
    servers = context.status.mcp_server_status()
    if not servers:
        context.ui.println("未配置 MCP")
        return
    connected = sum(1 for server in servers if server.connected)
    lines = [f"MCP 状态（{connected}/{len(servers)} 已连接）"]
    for server in servers:
        state = "已连接" if server.connected else "失败"
        suffix = f"  {server.error}" if server.error else ""
        lines.append(f"  {server.name}  [{state}]  {server.tool_count} tools{suffix}")
    context.ui.println("\n".join(lines))


MCP_COMMAND = Command(
    "mcp",
    "显示 MCP 服务器状态",
    CommandKind.LOCAL,
    handle_mcp,
    usage="/mcp",
)
