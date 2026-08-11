"""三级 YAML 权限配置与工具调用映射。"""

import json
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..llm import ToolCall
from .rules import Rule, RuleSet, parse_rule
from .types import Category


class SettingsError(ValueError):
    pass


class PermissionsBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    allow: list[str | dict[str, Any]] = Field(default_factory=list)
    ask: list[str | dict[str, Any]] = Field(default_factory=list)
    deny: list[str | dict[str, Any]] = Field(default_factory=list)

    @field_validator("allow", "ask", "deny", mode="before")
    @classmethod
    def _normalize_items(cls, value: object) -> object:
        """保留字符串规则；字典形式作为带作用域的对象规则。"""

        if not isinstance(value, list):
            return []
        return [
            item
            for item in value
            if isinstance(item, str) or isinstance(item, dict)
        ]


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_mode: str = ""
    permissions: PermissionsBlock = Field(default_factory=PermissionsBlock)


def load_settings(path: str) -> Settings:
    file = Path(path)
    if not file.is_file():
        return Settings()
    try:
        raw: Any = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SettingsError(str(exc)) from exc
    if not isinstance(raw, dict):
        raise SettingsError("权限配置必须是 YAML 对象")
    try:
        return Settings.model_validate(raw)
    except Exception as exc:
        raise SettingsError(str(exc)) from exc


def to_rule_set(settings: Settings) -> RuleSet:
    result = RuleSet()
    for value, allow, destination in (
        *[(value, True, result.allow) for value in settings.permissions.allow],
        *[(value, True, result.ask) for value in settings.permissions.ask],
        *[(value, False, result.deny) for value in settings.permissions.deny],
    ):
        rule, ok = _parse_setting_item(value, allow)
        if ok:
            destination.append(rule)
    return result


def _parse_setting_item(
    value: str | dict[str, Any],
    allow: bool,
) -> tuple[Rule, bool]:
    """解析字符串或对象形式的规则条目。"""

    if isinstance(value, str):
        return parse_rule(value, allow)
    tool = value.get("tool")
    pattern = value.get("pattern", "")
    scope = value.get("scope", "global")
    if not isinstance(tool, str) or not tool:
        rule, _ = parse_rule("", allow)
        return rule, False
    if not isinstance(pattern, str):
        pattern = ""
    if not isinstance(scope, str):
        scope = "global"
    rule, ok = parse_rule(tool, allow, scope)
    if not ok:
        return rule, False
    return Rule(tool, pattern, allow, scope), True


def friendly_name(name: str) -> str:
    return {
        "bash": "Bash",
        "read_file": "Read",
        "write_file": "Write",
        "edit_file": "Edit",
        "glob": "Glob",
        "grep": "Grep",
    }.get(name, name)


def categorize(name: str, read_only: bool) -> Category:
    if read_only:
        return Category.READ
    return Category.WRITE if name in {"write_file", "edit_file"} else Category.EXEC


def extract_target(call: ToolCall) -> tuple[str, bool, bool]:
    file_tools = {"read_file", "write_file", "edit_file", "glob", "grep"}
    if call.name not in file_tools | {"bash"}:
        return "", False, False
    try:
        data = json.loads(call.input or "{}")
    except (json.JSONDecodeError, TypeError):
        return "", call.name in file_tools, False
    if not isinstance(data, dict):
        return "", call.name in file_tools, False
    if call.name == "bash":
        command = data.get("command")
        if not isinstance(command, str):
            return "", False, False
        return command, False, bool(command)
    default = "." if call.name in {"glob", "grep"} else ""
    path = data.get("path", default)
    if not isinstance(path, str):
        return "", True, False
    return path, True, bool(path)
