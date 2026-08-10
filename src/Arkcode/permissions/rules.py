"""权限规则解析与 glob 匹配。"""

import re
from dataclasses import dataclass, field

from .types import Decision


@dataclass(frozen=True)
class Rule:
    tool: str
    pattern: str
    allow: bool


@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    ask: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def match(self, friendly: str, target: str) -> tuple[Decision, bool]:
        for rule in self.deny:
            if match_pattern(rule.tool, friendly) and match_pattern(
                rule.pattern, target
            ):
                return Decision.DENY, True
        for rule in self.ask:
            if match_pattern(rule.tool, friendly) and match_pattern(
                rule.pattern, target
            ):
                return Decision.ASK, True
        for rule in self.allow:
            if match_pattern(rule.tool, friendly) and match_pattern(
                rule.pattern, target
            ):
                return Decision.ALLOW, True
        return Decision.ALLOW, False


def parse_rule(value: str, allow: bool = True) -> tuple[Rule, bool]:
    match = re.fullmatch(r"([A-Za-z0-9_*-]+)(?:\((.*)\))?", value.strip())
    if match is None or not match.group(1):
        return Rule("", "", allow), False
    return Rule(match.group(1), match.group(2) or "", allow), True


def match_pattern(pattern: str, target: str) -> bool:
    if not pattern:
        return True
    path_pattern = "/" in pattern
    pieces: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern[index] == "\\" and index + 1 < len(pattern):
            pieces.append(re.escape(pattern[index + 1]))
            index += 2
        elif pattern[index : index + 2] == "**":
            pieces.append(".*")
            index += 2
        elif pattern[index] == "*":
            pieces.append("[^/]*" if path_pattern else ".*")
            index += 1
        else:
            pieces.append(re.escape(pattern[index]))
            index += 1
    return re.fullmatch("".join(pieces), target) is not None
