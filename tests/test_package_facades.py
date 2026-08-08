"""公共包门面应保持兼容，并把实现留在专用模块中。"""

from Arkcode.agent import Agent, Mode
from Arkcode.agent.agent import Agent as AgentImplementation
from Arkcode.llm import Request, new_provider
from Arkcode.llm.factory import new_provider as new_provider_implementation
from Arkcode.llm.types import Request as RequestImplementation
from Arkcode.permission import Engine
from Arkcode.permission.engine import Engine as EngineImplementation
from Arkcode.prompt import build_system_prompt
from Arkcode.prompt.builder import (
    build_system_prompt as build_system_prompt_implementation,
)
from Arkcode.skills import SkillExecutor, SkillLoader, SkillMeta, SkillSource
from Arkcode.tool import InstallSkillTool, LoadSkillTool


def test_package_facades_reexport_implementations() -> None:
    assert Agent is AgentImplementation
    assert Mode.__module__ == "Arkcode.permission.types"
    assert Request is RequestImplementation
    assert new_provider is new_provider_implementation
    assert Engine is EngineImplementation
    assert build_system_prompt is build_system_prompt_implementation


def test_skill_public_facades_use_skill_meta_as_the_only_metadata_name() -> None:
    import Arkcode.command as command_facade
    import Arkcode.skills as skills_facade
    import Arkcode.tool as tool_facade

    assert SkillMeta.__name__ == "SkillMeta"
    assert SkillLoader.__name__ == "SkillLoader"
    assert SkillExecutor.__name__ == "SkillExecutor"
    assert SkillSource.__name__ == "SkillSource"
    assert LoadSkillTool.__name__ == "LoadSkillTool"
    assert InstallSkillTool.__name__ == "InstallSkillTool"
    assert not hasattr(skills_facade, "Skill" + "Def")
    assert hasattr(command_facade, "register_skill_commands")
    assert hasattr(tool_facade, "InstallSkillTool")
