"""Agent 定义文件的 Markdown + YAML frontmatter 解析。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .models import Definition, Source

NAME_RE = re.compile(r"^[a-z0-9-]+$")
PERMISSION_MODES = {
    "default",
    "acceptEdits",
    "plan",
    "bypassPermissions",
    "dontAsk",
}


class DefinitionParseError(ValueError):
    """Agent 定义文件格式或字段非法。"""


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    stripped = content.lstrip()
    if not stripped.startswith("---"):
        raise DefinitionParseError("缺少 frontmatter 起始分隔符")
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        raise DefinitionParseError("缺少 frontmatter 结束分隔符")
    try:
        metadata = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise DefinitionParseError(f"frontmatter YAML 非法: {exc}") from exc
    if not isinstance(metadata, dict):
        raise DefinitionParseError("frontmatter 必须是 YAML 对象")
    return metadata, parts[2]


def _string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise DefinitionParseError(f"{field} 必须是字符串数组")
    return [item for item in value if item]


def parse_definition(
    content: str,
    *,
    name_hint: str = "",
    source: Source = Source.BUILTIN,
) -> Definition:
    """解析定义文本；任何字段非法都抛出 DefinitionParseError。"""

    metadata, body = _split_frontmatter(content)
    name = metadata.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DefinitionParseError("name 必须是非空字符串")
    name = name.strip()
    if not 1 <= len(name) <= 32 or NAME_RE.fullmatch(name) is None:
        raise DefinitionParseError(
            f"name {name!r} 必须匹配 ^[a-z0-9-]+$ 且长度 1-32"
        )
    if name_hint and name != name_hint:
        raise DefinitionParseError(f"frontmatter name 与文件名 {name_hint!r} 不一致")
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        raise DefinitionParseError("description 必须是非空字符串")
    model = metadata.get("model", "inherit")
    if not isinstance(model, str):
        raise DefinitionParseError("model 必须是字符串")
    max_turns = metadata.get("maxTurns", 25)
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
        raise DefinitionParseError("maxTurns 必须是正整数")
    permission_mode = metadata.get("permissionMode", "default")
    if not isinstance(permission_mode, str) or permission_mode not in PERMISSION_MODES:
        raise DefinitionParseError(
            f"permissionMode {permission_mode!r} 不是合法取值"
        )
    background = metadata.get("background", False)
    if not isinstance(background, bool):
        raise DefinitionParseError("background 必须是布尔值")
    isolation = metadata.get("isolation", "")
    if not isinstance(isolation, str) or isolation not in {"", "worktree"}:
        isolation = ""
    plan_required = metadata.get(
        "plan_mode_required",
        metadata.get("planModeRequired", False),
    )
    if not isinstance(plan_required, bool):
        raise DefinitionParseError("plan_mode_required 必须是布尔值")
    return Definition(
        name=name,
        description=description.strip(),
        instructions_content=body.strip(),
        tools=tuple(_string_list(metadata.get("tools"), "tools")),
        disallowed_tools=tuple(
            _string_list(metadata.get("disallowedTools"), "disallowedTools")
        ),
        model=model,
        max_turns=max_turns,
        permission_mode=permission_mode,
        background=background,
        isolation=isolation,
        plan_mode_required=plan_required,
        source=source,
    )


def parse_definition_file(
    path: str | Path,
    *,
    source: Source = Source.BUILTIN,
) -> Definition:
    file = Path(path)
    try:
        content = file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DefinitionParseError(f"无法读取定义文件 {file}: {exc}") from exc
    return parse_definition(
        content,
        name_hint=file.stem,
        source=source,
    )
