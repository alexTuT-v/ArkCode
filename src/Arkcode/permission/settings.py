"""三级 YAML 权限配置与工具调用映射。"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from ..llm import ToolCall
from .rule import RuleSet, parse_rule
from .types import Category


class SettingsError(ValueError):
    pass


@dataclass
class PermissionsBlock:
    allow: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class Settings:
    default_mode: str = ""
    permissions: PermissionsBlock = field(default_factory=PermissionsBlock)


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


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
    permissions = raw.get("permissions") or {}
    if not isinstance(permissions, dict):
        raise SettingsError("permissions 必须是对象")
    mode = raw.get("default_mode", "")
    return Settings(
        default_mode=mode if isinstance(mode, str) else "",
        permissions=PermissionsBlock(
            allow=_strings(permissions.get("allow")),
            ask=_strings(permissions.get("ask")),
            deny=_strings(permissions.get("deny")),
        ),
    )


def to_rule_set(settings: Settings) -> RuleSet:
    result = RuleSet()
    for value, allow, destination in (
        *[(value, True, result.allow) for value in settings.permissions.allow],
        *[(value, True, result.ask) for value in settings.permissions.ask],
        *[(value, False, result.deny) for value in settings.permissions.deny],
    ):
        rule, ok = parse_rule(value, allow)
        if ok:
            destination.append(rule)
    return result


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
