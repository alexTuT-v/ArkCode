"""工具注册表懒加载扩展测试。"""

from pydantic import BaseModel

from Arkcode.tools.base import Tool
from Arkcode.tools.registry import Registry


class _Params(BaseModel):
    pass


class DeferredTool(Tool[_Params]):
    read_only = True
    should_defer = True
    params_model = _Params

    def name(self) -> str:
        return "deferred_demo"

    def description(self) -> str:
        return "demo"

    async def execute(self, params: _Params):
        return None


class RankedDeferredTool(DeferredTool):
    def __init__(self, tool_name: str, tool_description: str) -> None:
        self._tool_name = tool_name
        self._tool_description = tool_description

    def name(self) -> str:
        return self._tool_name

    def description(self) -> str:
        return self._tool_description


def test_deferred_tools_excluded_until_discovered() -> None:
    registry = Registry()
    registry.register(DeferredTool())

    assert [item.name for item in registry.definitions()] == []
    assert registry.get_deferred_tool_names() == ["deferred_demo"]

    registry.mark_discovered("deferred_demo")

    assert [item.name for item in registry.definitions()] == ["deferred_demo"]
    assert registry.get_deferred_tool_names() == []


def test_search_deferred_scores_by_name_and_description() -> None:
    registry = Registry()
    registry.register(DeferredTool())

    found = registry.search_deferred("demo", 5)

    assert found[0]["name"] == "deferred_demo"
    assert (
        registry.find_deferred_by_names(["deferred_demo"])[0]["input_schema"]
        is not None
    )


def test_search_deferred_skips_discovered() -> None:
    registry = Registry()
    registry.register(DeferredTool())
    registry.mark_discovered("deferred_demo")

    assert registry.search_deferred("demo", 5) == []


def test_search_deferred_adds_word_level_scores() -> None:
    registry = Registry()
    registry.register(RankedDeferredTool("github_issue_search", "remote tool"))
    registry.register(RankedDeferredTool("github_client", "search repository issues"))
    registry.register(RankedDeferredTool("unrelated", "calendar events"))

    found = registry.search_deferred("github issue search", 5)

    assert [item["name"] for item in found] == [
        "github_issue_search",
        "github_client",
    ]


def test_search_deferred_keeps_registration_order_for_ties_and_applies_limit() -> None:
    registry = Registry()
    registry.register(RankedDeferredTool("first_alpha", "shared"))
    registry.register(RankedDeferredTool("second_alpha", "shared"))

    found = registry.search_deferred("alpha", 1)

    assert [item["name"] for item in found] == ["first_alpha"]


def test_search_deferred_rejects_blank_query() -> None:
    registry = Registry()
    registry.register(RankedDeferredTool("anything", "anything"))

    assert registry.search_deferred("   ", 5) == []
