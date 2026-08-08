"""Skill frontmatter 与正文解析。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import yaml  # type: ignore[import-untyped]

SkillMode = Literal["inline", "fork"]
SkillContext = Literal["full", "recent", "none"]


class SkillParseError(ValueError):
    """Skill 文件格式或元数据无效。"""


@dataclass(frozen=True, slots=True)
class SkillMeta:
    name: str
    description: str
    prompt_body: str
    mode: SkillMode = "inline"
    model: str | None = None
    context: SkillContext = "full"
    source_path: Path = Path()
    is_directory: bool = False


def parse_frontmatter(raw: str) -> tuple[dict[str, object], str]:
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise SkillParseError("missing frontmatter opening delimiter")
    closing = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if closing is None:
        raise SkillParseError("missing frontmatter closing delimiter")
    source = "".join(lines[1:closing])
    try:
        metadata = yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise SkillParseError(f"invalid YAML: {error}") from error
    if not isinstance(metadata, dict):
        raise SkillParseError("frontmatter must be a mapping")
    return cast(dict[str, object], metadata), "".join(lines[closing + 1 :])


def _required_string(metadata: dict[str, object], field: str) -> str:
    value = metadata.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SkillParseError(f"{field} must be a non-empty string")
    return value.strip()


def _validate_meta(
    metadata: dict[str, object],
) -> tuple[
    str,
    str,
    SkillMode,
    str | None,
    SkillContext,
]:
    import re

    name = _required_string(metadata, "name")
    if re.fullmatch(r"[a-z][a-z0-9-]*", name) is None:
        raise SkillParseError("name must match ^[a-z][a-z0-9-]*$")
    description = _required_string(metadata, "description")
    mode = metadata.get("mode", "inline")
    if mode not in {"inline", "fork"}:
        raise SkillParseError("mode must be inline or fork")
    context = metadata.get("context", "full")
    if context not in {"full", "recent", "none"}:
        raise SkillParseError("context must be full, recent, or none")
    model = metadata.get("model")
    if model is not None and not isinstance(model, str):
        raise SkillParseError("model must be a string")
    return (
        name,
        description,
        mode,
        model.strip() if isinstance(model, str) and model.strip() else None,
        context,
    )


def parse_skill_file(path: Path, *, is_directory: bool = False) -> SkillMeta:
    resolved = path.resolve()
    try:
        raw = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SkillParseError(f"failed to read skill file: {error}") from error
    metadata, body = parse_frontmatter(raw)
    name, description, mode, model, context = _validate_meta(metadata)
    return SkillMeta(
        name=name,
        description=description,
        prompt_body=body,
        mode=mode,
        model=model,
        context=context,
        source_path=resolved,
        is_directory=is_directory,
    )


def substitute_arguments(prompt_body: str, args: str) -> str:
    return prompt_body.replace("$ARGUMENTS", args)
