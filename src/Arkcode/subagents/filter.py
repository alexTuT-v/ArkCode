"""RegistryPolicy 与按身份隔离的 RegistryView。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tools import DEFAULT_TIMEOUT, Registry, ToolSearchTool
from ..tools.base import Result, ToolDefinition


@dataclass(frozen=True, slots=True)
class RegistryPolicy:
    """一个子 Agent 的工具过滤策略。"""

    globally_denied: frozenset[str]
    allowed: frozenset[str] | None = None
    denied: frozenset[str] = frozenset()
    background_allowed: frozenset[str] | None = None
    keep_agent_schema: bool = False


ALL_AGENT_DISALLOWED_TOOLS = frozenset({"Agent"})
CUSTOM_AGENT_DISALLOWED_TOOLS: frozenset[str] = frozenset()
ASYNC_AGENT_ALLOWED_TOOLS = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "bash",
        "load_skill",
        "install_skill",
        "LoadSkill",
        "InstallSkill",
    }
)


class RegistryView(Registry):
    """每个 Agent 独立的工具视图：共享实现，隔离 discovered 与过滤。"""

    _policy: RegistryPolicy

    @classmethod
    def from_parent(
        cls,
        parent: Registry,
        policy: RegistryPolicy,
        *,
        copy_discovery: bool,
    ) -> RegistryView:
        view = cls()
        for name in parent._order:
            tool = parent._tools[name]
            if isinstance(tool, ToolSearchTool):
                tool = ToolSearchTool(view)
            view.register(tool)
        view._timeouts = dict(parent._timeouts)
        if copy_discovery:
            view._discovered = set(parent._discovered)
        view._policy = policy
        return view

    def _policy_allows(self, name: str) -> bool:
        policy = self._policy
        if name in policy.globally_denied:
            if policy.keep_agent_schema and name == "Agent":
                return True
            return False
        if policy.allowed is not None and name not in policy.allowed:
            return False
        if name in policy.denied:
            return False
        if (
            policy.background_allowed is not None
            and name not in policy.background_allowed
        ):
            return False
        return True

    def get_deferred_tool_names(self) -> list[str]:
        return [
            name
            for name in self._order
            if self._policy_allows(name)
            and self._is_deferred(self._tools[name])
            and name not in self._discovered
        ]

    def search_deferred(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        query_lower = query.strip().lower()
        if not query_lower:
            return []
        query_words = query_lower.split()
        scored: list[tuple[int, str, Any]] = []
        for name in self._order:
            tool = self._tools[name]
            if not self._policy_allows(name):
                continue
            if not self._is_deferred(tool) or name in self._discovered:
                continue
            name_lower = name.lower()
            description_lower = (tool.description() or "").lower()
            score = 0
            if query_lower in name_lower:
                score += 10
            if query_lower in description_lower:
                score += 5
            for word in query_words:
                if word in name_lower:
                    score += 3
                if word in description_lower:
                    score += 1
            if score > 0:
                scored.append((score, name, tool))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [tool.get_schema() for _, _, tool in scored[:max_results]]

    def find_deferred_by_names(self, names: list[str]) -> list[dict[str, Any]]:
        return [
            self._tools[name].get_schema()
            for name in names
            if name in self._tools
            and self._policy_allows(name)
            and self._is_deferred(self._tools[name])
            and name not in self._discovered
        ]

    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=name,
                description=self._tools[name].description(),
                input_schema=self._tools[name].get_schema()["input_schema"],
            )
            for name in self._order
            if self._policy_allows(name)
            and (
                not self._is_deferred(self._tools[name])
                or name in self._discovered
            )
        ]

    def read_only_definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=name,
                description=self._tools[name].description(),
                input_schema=self._tools[name].get_schema()["input_schema"],
            )
            for name in self._order
            if self._tools[name].read_only
            and self._policy_allows(name)
            and (
                not self._is_deferred(self._tools[name])
                or name in self._discovered
            )
        ]

    def is_read_only(self, name: str) -> bool:
        tool = self.get(name)
        return tool is not None and tool.read_only

    async def execute(
        self,
        name: str,
        args: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Result:
        if not self._policy_allows(name):
            return Result(content=f"工具不可用: {name}", is_error=True)
        return await super().execute(name, args, timeout=timeout)


def build_policy(
    *,
    tools: tuple[str, ...] = (),
    disallowed_tools: tuple[str, ...] = (),
    background: bool = False,
    fork: bool = False,
) -> RegistryPolicy:
    """按 F26-F30 的过滤顺序构造子 Agent 策略。"""

    globally_denied = set(ALL_AGENT_DISALLOWED_TOOLS) | set(
        CUSTOM_AGENT_DISALLOWED_TOOLS
    )
    denied = set(disallowed_tools)
    allowed: frozenset[str] | None = None
    background_allowed: frozenset[str] | None = None
    if tools:
        allowed = frozenset(tools)
    if background or fork:
        background_allowed = ASYNC_AGENT_ALLOWED_TOOLS
    return RegistryPolicy(
        globally_denied=frozenset(globally_denied),
        allowed=allowed,
        denied=frozenset(denied),
        background_allowed=background_allowed,
        keep_agent_schema=fork,
    )
