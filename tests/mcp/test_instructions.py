"""MCP instructions 段落生成测试。"""

from Arkcode.mcp.manager import Manager, _Session
from Arkcode.mcp.tool_adapter import McpTool


class Caller:
    async def call_tool(self, name: str, arguments: dict | None = None):
        return None


def _tool(server: str) -> McpTool:
    return McpTool(
        full_name=f"mcp__{server}__echo",
        remote_name="echo",
        tool_description="echo",
        input_schema={"type": "object"},
        _read_only=True,
        caller=Caller(),
    )


def test_instructions_text_lists_tools_when_no_instructions() -> None:
    manager = Manager()
    manager._sessions.append(_Session(name="demo", session=object()))
    manager._tools.append(_tool("demo"))

    text = manager.instructions_text()

    assert "# MCP Server Instructions" in text
    assert "## demo" in text
    assert "mcp__demo__echo" in text


def test_instructions_text_uses_provided_instructions() -> None:
    manager = Manager()
    manager._sessions.append(
        _Session(
            name="demo", session=object(), mcp_instructions="Use the API carefully"
        )
    )

    text = manager.instructions_text()

    assert "Use the API carefully" in text
    assert "Available tools" not in text


def test_instructions_text_empty_without_sessions() -> None:
    assert Manager().instructions_text() == ""
