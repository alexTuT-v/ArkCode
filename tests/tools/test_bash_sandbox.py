"""Bash 工具沙箱注入测试。"""

import pytest

from Arkcode.sandbox import Sandbox, SandboxConfig
from Arkcode.tools.builtins.bash import BashTool, Params


class FakeSandbox(Sandbox):
    def __init__(self) -> None:
        self.wrapped: list[tuple[str, SandboxConfig]] = []

    def wrap(self, command: str, config: SandboxConfig) -> str:
        self.wrapped.append((command, config))
        return command

    def available(self) -> bool:
        return True


def test_bash_wraps_command_when_sandbox_injected() -> None:
    sandbox = FakeSandbox()
    tool = BashTool(sandbox=sandbox, sandbox_config=SandboxConfig())

    assert tool.sandbox is sandbox
    assert tool.sandbox_config is not None


def test_bash_defaults_to_no_sandbox() -> None:
    tool = BashTool()

    assert tool.sandbox is None
    assert tool.sandbox_config is None


@pytest.mark.asyncio
async def test_bash_execute_invokes_sandbox_wrap() -> None:
    sandbox = FakeSandbox()
    tool = BashTool(sandbox=sandbox, sandbox_config=SandboxConfig())

    result = await tool.execute(Params(command="echo hello"))

    assert sandbox.wrapped[0][0] == "echo hello"
    assert result.is_error is False
