"""按名称加载 Skill，并将其 SOP 激活到主 Agent 上下文。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol

from .base import Result, Tool

if TYPE_CHECKING:
    from ..skills.loader import SkillLoader


class _SkillAgent(Protocol):
    """LoadSkill 所需的最小 Agent 能力。"""

    def activate_skill(self, name: str, body: str) -> None: ...


class LoadSkillTool(Tool):
    """让模型按需加载完整 Skill SOP，而不把正文放进工具结果。"""

    read_only = True

    def __init__(
        self,
        loader: SkillLoader | None = None,
        agent: _SkillAgent | None = None,
    ) -> None:
        self._loader = loader
        self._agent = agent

    def set_loader(self, loader: SkillLoader) -> None:
        self._loader = loader

    def set_agent(self, agent: _SkillAgent) -> None:
        self._agent = agent

    def name(self) -> str:
        return "LoadSkill"

    def description(self) -> str:
        return "Activate a local Skill SOP in the Agent environment context."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return Result("LoadSkill requires valid JSON arguments", is_error=True)

        if not isinstance(data, dict) or set(data) != {"name"}:
            return Result("LoadSkill requires exactly one 'name' field", is_error=True)
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            return Result("LoadSkill 'name' must be a non-empty string", is_error=True)
        name = name.strip().lower()

        if self._loader is None or self._agent is None:
            return Result("LoadSkill not properly initialized", is_error=True)

        skill = self._loader.get(name)
        if skill is None:
            available = ", ".join(item[0] for item in self._loader.get_catalog())
            suffix = available or "none"
            return Result(
                f"Unknown skill '{name}'. Available skills: {suffix}",
                is_error=True,
            )

        self._agent.activate_skill(skill.name, skill.prompt_body)
        return Result(
            f"Skill '{skill.name}' activated. SOP pinned to environment context."
        )
