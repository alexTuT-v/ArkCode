import asyncio
from typing import Any

import mcp.types as mtypes
import pytest

from Arkcode.mcp import tool as mcp_tool_module
from Arkcode.mcp.tool import McpTool, adapt_tool


class StubSession:
    def __init__(
        self,
        result: mtypes.CallToolResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> mtypes.CallToolResult:
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _remote_tool(
    *,
    name: str = "echo",
    description: str | None = "Echo input",
    schema: dict[str, Any] | None = None,
    read_only: bool | None = None,
) -> mtypes.Tool:
    annotations = (
        None if read_only is None else mtypes.ToolAnnotations(readOnlyHint=read_only)
    )
    return mtypes.Tool(
        name=name,
        description=description,
        inputSchema=schema or {},
        annotations=annotations,
    )


def test_adapt_tool_exposes_namespaced_definition_and_read_only_hint() -> None:
    session = StubSession()
    adapted = adapt_tool(
        "demo",
        _remote_tool(
            description=None,
            schema={"type": "object", "properties": {"value": {"type": "string"}}},
            read_only=True,
        ),
        session,
    )

    assert isinstance(adapted, McpTool)
    assert adapted.name() == "mcp__demo__echo"
    assert "demo" in adapted.description()
    assert adapted.parameters() == {
        "type": "object",
        "properties": {"value": {"type": "string"}},
    }
    assert adapted.read_only is True


def test_adapt_tool_rejects_illegal_full_name_and_defaults_empty_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = StubSession()

    invalid = adapt_tool("bad.server", _remote_tool(), session)
    valid = adapt_tool("good", _remote_tool(schema={}), session)

    assert invalid is None
    assert valid is not None
    assert valid.parameters() == {"type": "object"}
    assert valid.read_only is False
    assert "illegal characters" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_execute_parses_json_and_joins_text_in_order() -> None:
    session = StubSession(
        mtypes.CallToolResult(
            content=[
                mtypes.TextContent(text="first"),
                mtypes.TextContent(text="second"),
            ]
        )
    )
    tool = adapt_tool("demo", _remote_tool(), session)
    assert tool is not None

    result = await tool.execute('{"value": "hello"}')

    assert result.content == "first\nsecond"
    assert result.is_error is False
    assert session.calls == [("echo", {"value": "hello"})]


@pytest.mark.asyncio
async def test_execute_maps_remote_error_and_drops_non_text_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    mcp_tool_module._non_text_warn_once.clear()
    session = StubSession(
        mtypes.CallToolResult(
            content=[
                mtypes.ImageContent(data="aGVsbG8=", mimeType="image/png"),
                mtypes.TextContent(text="remote failure"),
            ],
            isError=True,
        )
    )
    tool = adapt_tool("demo", _remote_tool(), session)
    assert tool is not None

    first = await tool.execute("{}")
    second = await tool.execute("{}")

    assert first.content == "remote failure"
    assert first.is_error is True
    assert second.is_error is True
    assert capsys.readouterr().err.count("non-text content") == 1


@pytest.mark.asyncio
async def test_execute_reports_bad_json_and_protocol_failure() -> None:
    session = StubSession(error=RuntimeError("connection lost"))
    tool = adapt_tool("demo", _remote_tool(), session)
    assert tool is not None

    bad_json = await tool.execute("not-json")
    failed = await tool.execute("{}")

    assert bad_json.is_error is True
    assert "JSON" in bad_json.content
    assert failed.is_error is True
    assert "connection lost" in failed.content


@pytest.mark.asyncio
async def test_execute_times_out_without_leaking_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingSession:
        async def call_tool(
            self, name: str, arguments: dict[str, Any] | None = None
        ) -> mtypes.CallToolResult:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    monkeypatch.setattr(mcp_tool_module, "call_timeout", 0.01)
    tool = adapt_tool("demo", _remote_tool(), BlockingSession())
    assert tool is not None

    result = await tool.execute("{}")

    assert result.is_error is True
    assert "超时" in result.content
