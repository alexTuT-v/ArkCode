"""供 MCP 客户端端到端测试使用的真实 stdio server。"""

import os

import mcp.types as mtypes
from mcp.server.mcpserver import MCPServer

server = MCPServer("arkcode-test-server", version="1.0")


@server.tool(annotations=mtypes.ToolAnnotations(readOnlyHint=True))
def echo(value: str) -> str:
    """返回进程、环境与输入，供客户端边界验证。"""

    injected = os.environ.get("ARKCODE_MCP_TEST_VALUE", "missing")
    return f"{os.getpid()}|{injected}|{value}"


if __name__ == "__main__":
    server.run(transport="stdio")
