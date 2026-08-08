"""远程 Skill 安装工具。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .base import Result, Tool

if TYPE_CHECKING:
    from ..skills.install import SkillSource


class _ReloadingLoader(Protocol):
    def reload(self) -> object: ...


def parse_skill_url(url: str) -> SkillSource:
    from ..skills.install import parse_skill_url as parse

    return parse(url)


async def install_skill(source: SkillSource, install_root: Path) -> str:
    from ..skills.install import install_skill as install

    return await install(source, install_root)


class InstallSkillTool(Tool):
    """安装受支持 URL 指向的 Skill，并立即刷新运行时目录。"""

    read_only = False

    def __init__(
        self,
        loader: _ReloadingLoader | None = None,
        install_root: Path | None = None,
        on_installed: Callable[[], None] | None = None,
    ) -> None:
        self._loader = loader
        self._install_root = install_root or Path.home() / ".Arkcode" / "skills"
        self._on_installed = on_installed

    def name(self) -> str:
        return "InstallSkill"

    def description(self) -> str:
        return "Install a Skill from a supported HTTPS URL."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return Result("InstallSkill requires valid JSON arguments", is_error=True)
        if not isinstance(data, dict) or set(data) != {"url"}:
            return Result(
                "InstallSkill requires exactly one 'url' field",
                is_error=True,
            )
        url = data.get("url")
        if not isinstance(url, str) or not url.strip():
            return Result(
                "InstallSkill 'url' must be a non-empty string",
                is_error=True,
            )
        try:
            source = parse_skill_url(url.strip())
        except Exception as error:
            return Result(f"Invalid Skill URL: {error}", is_error=True)
        if self._loader is None:
            return Result("InstallSkill not properly initialized", is_error=True)

        try:
            name = await install_skill(source, self._install_root)
            self._loader.reload()
            if self._on_installed is not None:
                self._on_installed()
        except Exception as error:
            return Result(f"InstallSkill failed: {error}", is_error=True)
        return Result(f"Skill '{name}' installed and registered.")
