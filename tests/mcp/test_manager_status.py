"""Manager.server_summary 状态汇总测试。"""

from typing import Any

from Arkcode.mcp.manager import Manager, McpServerStatus, _Session
from Arkcode.mcp.tool_adapter import McpTool


class Caller:
    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> None:
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


def test_server_summary_reports_connected_and_failed() -> None:
    manager = Manager(configured_servers=2)
    manager._sessions.append(_Session(name="demo", session=object()))
    manager._tools.append(_tool("demo"))
    manager._failures["broken"] = "connect refused"

    summary = manager.server_summary()

    assert summary == [
        McpServerStatus(
            name="broken",
            tool_count=0,
            connected=False,
            error="connect refused",
        ),
        McpServerStatus(name="demo", tool_count=1, connected=True, error=None),
    ]


def test_server_summary_empty_when_no_servers() -> None:
    manager = Manager()

    assert manager.server_summary() == []
