import asyncio
from typing import Any

import mcp.types as mtypes
import pytest

from Arkcode.mcp import tool_adapter as mcp_tool_module
from Arkcode.mcp.tool_adapter import (
    McpTool,
    _build_params_model,
    _extract_text,
    adapt_tool,
)


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
    schema = adapted.get_schema()["input_schema"]
    assert "value" in schema["properties"]
    assert schema.get("required", []) == []
    assert adapted.read_only is True


def test_adapt_tool_preserves_original_complex_input_schema() -> None:
    original = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["fast", "safe"],
                "description": "Execution mode",
            },
            "filters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
            },
            "target": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "integer"},
                ]
            },
        },
        "required": ["mode"],
        "additionalProperties": False,
    }
    tool = adapt_tool("demo", _remote_tool(schema=original), StubSession())

    assert tool is not None
    assert tool.get_schema() == {
        "name": "mcp__demo__echo",
        "description": "Echo input",
        "input_schema": original,
    }
    assert tool.input_schema == original


def test_adapt_tool_rejects_illegal_full_name_and_defaults_empty_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = StubSession()

    invalid = adapt_tool("bad.server", _remote_tool(), session)
    valid = adapt_tool("good", _remote_tool(schema={}), session)

    assert invalid is None
    assert valid is not None
    assert valid.get_schema()["input_schema"]["type"] == "object"
    assert valid.read_only is False
    assert "illegal characters" in capsys.readouterr().err


def test_build_params_model_maps_types_and_required() -> None:
    model = _build_params_model(
        "demo",
        {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "name": {"type": "string"},
                "flag": {"type": "boolean"},
            },
            "required": ["name"],
        },
    )

    instance = model.model_validate({"name": "x", "count": "3", "flag": "true"})
    assert instance.model_dump(exclude_none=True) == {
        "name": "x",
        "count": 3,
        "flag": True,
    }

    with pytest.raises(Exception):
        model.model_validate({"count": 1})


def test_extract_text_handles_rich_blocks() -> None:
    text = mtypes.TextContent(type="text", text="hello")
    image = mtypes.ImageContent(type="image", data="...", mimeType="image/png")
    resource = mtypes.EmbeddedResource(
        type="resource",
        resource=mtypes.TextResourceContents(
            uri="file:///a.txt",
            text="content",
        ),
    )

    assert _extract_text([text, image, resource]) == (
        "hello\n[image: image/png]\ncontent"
    )


def test_extract_text_empty_content() -> None:
    assert _extract_text([]) == "(no output)"


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

    result = await tool.execute(tool.params_model.model_validate({"value": "hello"}))

    assert result.content == "first\nsecond"
    assert result.is_error is False
    assert session.calls == [("echo", {"value": "hello"})]


@pytest.mark.asyncio
async def test_execute_maps_remote_error_and_extracts_rich_blocks() -> None:
    session = StubSession(
        mtypes.CallToolResult(
            content=[
                mtypes.ImageContent(data="aGVsbG8=", mime_type="image/png"),
                mtypes.TextContent(text="remote failure"),
            ],
            isError=True,
        )
    )
    tool = adapt_tool("demo", _remote_tool(), session)
    assert tool is not None

    result = await tool.execute(tool.params_model.model_validate({}))

    assert result.content == "[image: image/png]\nremote failure"
    assert result.is_error is True


@pytest.mark.asyncio
async def test_execute_reports_bad_json_and_protocol_failure() -> None:
    session = StubSession(error=RuntimeError("connection lost"))
    tool = adapt_tool("demo", _remote_tool(), session)
    assert tool is not None

    failed = await tool.execute(tool.params_model.model_validate({}))

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

    result = await tool.execute(tool.params_model.model_validate({}))

    assert result.is_error is True
    assert "超时" in result.content
