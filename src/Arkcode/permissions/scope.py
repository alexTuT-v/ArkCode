"""权限作用域、临时账本与带作用域的规则匹配。"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..llm import ToolCall
from .rules import Rule, match_pattern
from .settings import extract_target, friendly_name
from .types import Decision


@dataclass(frozen=True, slots=True)
class PermissionScope:
    """当前 Agent 的长期规则匹配作用域。"""

    value: str

    @classmethod
    def main(cls) -> PermissionScope:
        return cls("main-agent")

    @classmethod
    def subagent_type(cls, agent_type: str) -> PermissionScope:
        return cls(f"subagent-type:{agent_type}")

    @classmethod
    def subagent_instance(cls, agent_id: str) -> PermissionScope:
        return cls(f"subagent-instance:{agent_id}")


def _rule_for_call(call: ToolCall, allow: bool) -> Rule:
    target, is_file, _ = extract_target(call)
    return Rule(friendly_name(call.name), target if is_file else target, allow)


@dataclass(slots=True)
class PermissionLedger:
    """单个 Agent 独立的临时授权账本。"""

    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def record_allow(self, call: ToolCall) -> None:
        self.allow.append(_rule_for_call(call, True))

    def record_deny(self, call: ToolCall) -> None:
        self.deny.append(_rule_for_call(call, False))

    def match(self, friendly: str, target: str) -> tuple[Decision, bool]:
        for rule in self.deny:
            if match_pattern(rule.tool, friendly) and match_pattern(
                rule.pattern,
                target,
            ):
                return Decision.DENY, True
        for rule in self.allow:
            if match_pattern(rule.tool, friendly) and match_pattern(
                rule.pattern,
                target,
            ):
                return Decision.ALLOW, True
        return Decision.ALLOW, False


def scope_matches(rule_scope: str, current_scope: str) -> bool:
    """判断一条规则是否适用于当前作用域。"""

    if rule_scope in {"", "global"}:
        return True
    if rule_scope == current_scope:
        return True
    if rule_scope.startswith("subagent-type:") or rule_scope.startswith(
        "subagent-instance:"
    ):
        return False
    return False


def match_scoped_rules(
    rule_sets: tuple[object, ...],
    current_scope: str,
    friendly: str,
    target: str,
) -> tuple[Decision, bool]:
    """按 deny > ask > allow 顺序匹配带作用域的长期规则。"""

    for ruleset in rule_sets:
        for rule in getattr(ruleset, "deny", []):
            if not scope_matches(rule.scope, current_scope):
                continue
            if match_pattern(rule.tool, friendly) and match_pattern(
                rule.pattern,
                target,
            ):
                return Decision.DENY, True
    for ruleset in rule_sets:
        for rule in getattr(ruleset, "ask", []):
            if not scope_matches(rule.scope, current_scope):
                continue
            if match_pattern(rule.tool, friendly) and match_pattern(
                rule.pattern,
                target,
            ):
                return Decision.ASK, True
    for ruleset in rule_sets:
        for rule in getattr(ruleset, "allow", []):
            if not scope_matches(rule.scope, current_scope):
                continue
            if match_pattern(rule.tool, friendly) and match_pattern(
                rule.pattern,
                target,
            ):
                return Decision.ALLOW, True
    return Decision.ALLOW, False


class ScopedRuleStore:
    """兼容入口：把规则来源聚合为带作用域的匹配。"""

    def __init__(self, *rule_sets: object) -> None:
        self._rule_sets = tuple(rule_sets)

    def match(
        self,
        scope: PermissionScope,
        friendly: str,
        target: str,
    ) -> tuple[Decision, bool]:
        return match_scoped_rules(
            self._rule_sets,
            scope.value,
            friendly,
            target,
        )
