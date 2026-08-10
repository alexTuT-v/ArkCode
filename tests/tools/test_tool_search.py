"""ToolSearch 内置工具测试。"""

import pytest

from Arkcode.tools.builtins.tool_search import Params, ToolSearchTool
from Arkcode.tools.registry import Registry

from .test_deferred import DeferredTool


def make_registry_with_deferred() -> Registry:
    registry = Registry()
    registry.register(DeferredTool())
    return registry


@pytest.mark.asyncio
async def test_tool_search_select_loads_deferred_tool() -> None:
    registry = make_registry_with_deferred()
    tool = ToolSearchTool(registry)

    result = await tool.execute(Params(query="select:deferred_demo"))

    assert result.is_error is False
    assert "deferred_demo" in result.content
    assert [item.name for item in registry.definitions()] == ["deferred_demo"]


@pytest.mark.asyncio
async def test_tool_search_keyword_lists_matches() -> None:
    registry = make_registry_with_deferred()
    tool = ToolSearchTool(registry)

    result = await tool.execute(Params(query="demo"))

    assert "Found 1 tool" in result.content


@pytest.mark.asyncio
async def test_tool_search_no_match_lists_available() -> None:
    registry = make_registry_with_deferred()
    tool = ToolSearchTool(registry)

    result = await tool.execute(Params(query="nothing"))

    assert "deferred_demo" in result.content


@pytest.mark.asyncio
async def test_tool_search_blank_query_discovers_nothing() -> None:
    registry = make_registry_with_deferred()
    tool = ToolSearchTool(registry)

    result = await tool.execute(Params(query="   "))

    assert "No matching deferred tools" in result.content
    assert "deferred_demo" in result.content
    assert registry.is_discovered("deferred_demo") is False


def test_tool_search_itself_is_not_deferred() -> None:
    assert ToolSearchTool.should_defer is False
