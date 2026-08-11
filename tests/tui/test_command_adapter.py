"""CommandUIAdapter 四端口实现测试。"""

from __future__ import annotations

from Arkcode.commands import CommandContext, dispatch, parse, register_builtins
from Arkcode.permissions import Mode
from Arkcode.sandbox import Sandbox, SandboxConfig
from Arkcode.tui.adapters.command_ui import CommandUIAdapter

from .fakes import FakeApp, FakeSession


def make_adapter() -> tuple[CommandUIAdapter, FakeApp, FakeSession]:
    app = FakeApp()
    session = FakeSession()
    return CommandUIAdapter(app, session), app, session


def test_adapter_implements_display_port() -> None:
    adapter, app, _ = make_adapter()

    adapter.println("hello")
    adapter.error("boom")
    adapter.request_exit()

    assert app.log.lines
    assert app.exited == 1


def test_adapter_implements_session_port() -> None:
    adapter, app, session = make_adapter()
    adapter.set_mode(Mode.PLAN)
    adapter.clear_session()

    assert session.mode is Mode.PLAN
    assert session.cleared == 1
    assert app.usage_in == app.usage_out == 0


def test_adapter_implements_status_port() -> None:
    adapter, app, session = make_adapter()
    app.usage_in = 12
    app.usage_out = 3

    assert adapter.usage() == (12, 3)
    assert adapter.cwd() == "/workspace"
    assert adapter.session_id() == "id"
    assert adapter.model_name() == ""


def test_adapter_dispatch_roundtrip_with_builtins() -> None:
    adapter, app, session = make_adapter()
    registry = app.cmd_registry
    register_builtins(registry)

    async def run_dispatch() -> bool:
        name, args, is_slash = parse("/status")
        assert is_slash is True
        context = CommandContext(
            args=args,
            session=adapter,
            skills=adapter,
            status=adapter,
            ui=adapter,
            sandbox=adapter,
        )
        return await dispatch(registry, name, context)

    import asyncio

    assert asyncio.run(run_dispatch()) is True
    assert any("ArkCode Status" in line.plain for line in app.log.lines)


class FakeSandbox(Sandbox):
    def wrap(self, command: str, config: SandboxConfig) -> str:
        return command

    def available(self) -> bool:
        return True


class FakeEngine:
    def __init__(self) -> None:
        self.sandbox_enabled = False


def test_adapter_sandbox_enable_hooks_bash_and_engine(monkeypatch) -> None:
    fake_sandbox = FakeSandbox()
    monkeypatch.setattr("Arkcode.sandbox.create_sandbox", lambda: fake_sandbox)
    app = FakeApp()
    session = FakeSession()
    session.permissions = FakeEngine()
    adapter = CommandUIAdapter(app, session)

    error = adapter.enable(True)

    assert error is None
    bash = app.tool_registry.get("bash")
    assert bash is not None
    assert getattr(bash, "sandbox", None) is fake_sandbox
    assert session.permissions.sandbox_enabled is True

    adapter.disable()

    assert getattr(bash, "sandbox", None) is None
    assert session.permissions.sandbox_enabled is False
