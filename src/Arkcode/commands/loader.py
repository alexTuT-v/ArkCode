"""从 .Arkcode/commands/ 加载自定义 Markdown 命令。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .models import Command, CommandContext, CommandKind, Handler
from .registry import CommandRegistry

logger = logging.getLogger(__name__)


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """分离 YAML frontmatter 与 Markdown 正文。"""

    stripped = content.lstrip()
    if not stripped.startswith("---"):
        return {}, content
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        return {}, content
    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}, content
    if not isinstance(meta, dict):
        return {}, content
    return meta, parts[2]


def _command_name(root: Path, path: Path) -> str:
    """子目录映射为冒号命名空间：git/log.md -> git:log。"""

    relative = path.relative_to(root).with_suffix("")
    return ":".join(relative.parts)


def _make_prompt_handler(body: str, name: str) -> Handler:
    async def handler(context: CommandContext) -> None:
        rendered = body.replace("$ARGUMENTS", context.args)
        if "$ARGUMENTS" not in body and context.args:
            rendered = f"{rendered}\n\n## User Request\n{context.args}"
        context.session.submit_prompt(f"/{name}", rendered)

    return handler


def register_custom_commands(
    registry: CommandRegistry,
    work_dir: str | Path,
) -> None:
    """扫描 .Arkcode/commands/*.md 并注册为 PROMPT 命令。"""

    root = Path(work_dir).resolve() / ".Arkcode" / "commands"
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = _split_frontmatter(content)
        name = _command_name(root, path)
        description = str(meta.get("description") or name)
        aliases = meta.get("aliases")
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, list) or not all(
            isinstance(item, str) for item in aliases
        ):
            aliases = []
        argument_hint = str(meta.get("argument-hint", ""))
        command = Command(
            name,
            description,
            CommandKind.PROMPT,
            _make_prompt_handler(body, name),
            aliases=aliases,
            usage=f"/{name} [args]",
            arg_prompt=argument_hint,
        )
        try:
            registry.register(command)
        except (RuntimeError, ValueError) as error:
            logger.warning("跳过自定义命令 %s：%s", name, error)
