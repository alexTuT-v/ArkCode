"""永久精确放行规则写入。"""

from pathlib import Path
from typing import TYPE_CHECKING

import yaml  # type: ignore[import-untyped]

from ..llm import ToolCall
from .rule import Rule
from .settings import extract_target, friendly_name, load_settings

if TYPE_CHECKING:
    from .engine import Engine


def _escape_glob(value: str) -> str:
    return value.replace("\\", "\\\\").replace("*", "\\*")


def rule_for(engine: "Engine", call: ToolCall) -> tuple[Rule, str, bool]:
    target, is_file, ok = extract_target(call)
    if not ok:
        return Rule("", "", True), "", False
    friendly = friendly_name(call.name)
    if is_file:
        try:
            path = Path(target)
            if path.is_absolute():
                target = path.relative_to(engine.root).as_posix()
            else:
                target = path.as_posix()
        except ValueError:
            return Rule("", "", True), "", False
    else:
        target = _escape_glob(target)
    value = f"{friendly}({target})"
    return Rule(friendly, target, True), value, True


def persist_local_allow(engine: "Engine", call: ToolCall) -> None:
    rule, value, ok = rule_for(engine, call)
    if not ok:
        raise ValueError("无法为工具调用生成永久规则")
    settings = load_settings(engine.local_path)
    if value not in settings.permissions.allow:
        settings.permissions.allow.append(value)
    path = Path(engine.local_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "default_mode": settings.default_mode or "default",
        "permissions": {
            "allow": settings.permissions.allow,
            "ask": settings.permissions.ask,
            "deny": settings.permissions.deny,
        },
    }
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    if rule not in engine.local.allow:
        engine.local.allow.append(rule)
