"""RegistryPolicy 与 RegistryView 过滤测试。"""

import asyncio

from pydantic import BaseModel

from Arkcode.subagents.filter import (
    RegistryPolicy,
    RegistryView,
    build_policy,
)
from Arkcode.tools import Registry, Result, Tool, ToolSearchTool


class EmptyParams(BaseModel):
    pass


class StubTool(Tool[EmptyParams]):
    read_only = True
    params_model = EmptyParams

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name

    def name(self) -> str:
        return self.tool_name

    def description(self) -> str:
        return f"工具 {self.tool_name}"

    async def execute(self, params: EmptyParams) -> Result:
        return Result(f"ok:{self.tool_name}")


class DeferredTool(StubTool):
    should_defer = True


def _registry() -> Registry:
    registry = Registry()
    registry.register(StubTool("Agent"))
    registry.register(StubTool("bash"))
    registry.register(StubTool("read_file"))
    registry.register(DeferredTool("mcp__srv__remote"))
    registry.register(ToolSearchTool(registry))
    return registry


def test_defined_view_hides_agent_and_respects_whitelist() -> None:
    parent = _registry()
    view = RegistryView.from_parent(
        parent,
        build_policy(tools=("read_file", "bash"), background=False),
        copy_discovery=False,
    )
    names = {definition.name for definition in view.definitions()}
    assert names == {"read_file", "bash"}
    assert "Agent" not in names


def test_defined_view_respects_deny_and_background_whitelist() -> None:
    parent = _registry()
    view = RegistryView.from_parent(
        parent,
        build_policy(
            disallowed_tools=("read_file",),
            background=True,
        ),
        copy_discovery=False,
    )
    names = {definition.name for definition in view.definitions()}
    assert "read_file" not in names
    assert "bash" in names
    assert "Agent" not in names


def test_fork_view_keeps_agent_schema_but_others_filtered() -> None:
    parent = _registry()
    view = RegistryView.from_parent(
        parent,
        build_policy(background=True, fork=True),
        copy_discovery=True,
    )
    names = {definition.name for definition in view.definitions()}
    assert "Agent" in names
    assert "bash" in names


def test_discovered_state_is_independent_per_view() -> None:
    parent = _registry()
    first = RegistryView.from_parent(
        parent,
        build_policy(),
        copy_discovery=False,
    )
    second = RegistryView.from_parent(
        parent,
        build_policy(),
        copy_discovery=False,
    )
    first.mark_discovered("mcp__srv__remote")
    assert first.is_discovered("mcp__srv__remote")
    assert not second.is_discovered("mcp__srv__remote")
    assert not parent.is_discovered("mcp__srv__remote")


def test_deferred_tools_cannot_bypass_policy() -> None:
    parent = _registry()
    policy = RegistryPolicy(
        globally_denied=frozenset({"Agent"}),
        allowed=frozenset({"read_file", "bash"}),
        denied=frozenset(),
        background_allowed=None,
    )
    view = RegistryView.from_parent(parent, policy, copy_discovery=False)
    assert view.search_deferred("remote", 5) == []
    assert view.find_deferred_by_names(["mcp__srv__remote"]) == []
    result = asyncio.run(view.execute("mcp__srv__remote", "{}"))
    assert result.is_error


def test_toolsearch_is_rebound_to_view() -> None:
    parent = _registry()
    view = RegistryView.from_parent(parent, build_policy(), copy_discovery=False)
    tool = view.get("ToolSearch")
    assert isinstance(tool, ToolSearchTool)
    assert tool._registry is view
