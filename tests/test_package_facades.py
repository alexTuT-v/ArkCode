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


def test_package_facades_reexport_implementations() -> None:
    assert Agent is AgentImplementation
    assert Mode.__module__ == "Arkcode.permission.types"
    assert Request is RequestImplementation
    assert new_provider is new_provider_implementation
    assert Engine is EngineImplementation
    assert build_system_prompt is build_system_prompt_implementation
