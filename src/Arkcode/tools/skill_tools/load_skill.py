"""按名称加载 Skill，并将其 SOP 激活到主 Agent 上下文。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..base import Result, Tool

if TYPE_CHECKING:
    from ...skills.loader import SkillLoader


class _SkillAgent(Protocol):
    """LoadSkill 所需的最小 Agent 能力。"""

    def activate_skill(self, name: str, body: str) -> None: ...


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Skill 名称")


class LoadSkillTool(Tool[Params]):
    """让模型按需加载完整 Skill SOP，而不把正文放进工具结果。"""

    read_only = True
    params_model = Params

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

    async def execute(self, params: Params) -> Result:
        name = params.name.strip().lower()

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
