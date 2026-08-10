"""TUI 渲染块单元测试。"""

from rich.console import Console

from Arkcode.mcp import McpStatus
from Arkcode.tui.streaming.state import ToolDisplay
from Arkcode.tui.views.messages import streaming_block
from Arkcode.tui.views.status import mcp_status_line
from Arkcode.tui.views.tools import tool_line, tool_result_summary


def rich_text(renderable: object) -> str:
    console = Console(width=100, record=True)
    console.print(renderable)
    return console.export_text()


def test_mcp_status_line_reports_partial_failure() -> None:
    line = mcp_status_line(McpStatus(2, 1, 3))

    assert line is not None
    assert rich_text(line).strip() == (
        "MCP 1/2 servers connected · 3 tools registered · 1 failed"
    )
    assert str(line.style) == "dim"
    assert any(str(span.style) == "yellow" for span in line.spans)


def test_mcp_status_line_omits_failure_when_all_servers_connect() -> None:
    line = mcp_status_line(McpStatus(2, 2, 5))

    assert line is not None
    assert rich_text(line).strip() == ("MCP 2/2 servers connected · 5 tools registered")


def test_mcp_status_line_is_absent_without_configured_servers() -> None:
    assert mcp_status_line(McpStatus(0, 0, 0)) is None


def test_tool_rendering_has_claude_code_style_and_bounded_summary() -> None:
    line = rich_text(tool_line("read_file", '{"path":"a.txt"}'))
    summary = rich_text(
        tool_result_summary("\n".join(f"line {index}" for index in range(20)), False)
    )
    error = rich_text(tool_result_summary("not found", True))

    assert "● read_file(" in line
    assert "⎿" in summary
    assert "[truncated]" in summary
    assert "not found" in error


def test_streaming_block_lists_multiple_running_tools_in_order() -> None:
    rendered = rich_text(
        streaming_block(
            "",
            2,
            [
                ToolDisplay("read_file", '{"path":"a"}'),
                ToolDisplay("grep", '{"pattern":"x"}'),
            ],
            3,
        )
    )

    assert rendered.index("read_file") < rendered.index("grep")
    assert rendered.count("Running") == 2
