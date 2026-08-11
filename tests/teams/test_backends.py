"""后端检测与三种 Backend 测试。"""

import asyncio
from pathlib import Path

import pytest

from Arkcode.subagents.manager import TaskManager
from Arkcode.teams.backends.detect import detect_backend, reset_backend_cache
from Arkcode.teams.backends.inprocess import InProcessBackend
from Arkcode.teams.backends.tmux import TmuxBackend
from Arkcode.teams.models import BackendType, SpawnRequest


@pytest.fixture(autouse=True)
def _reset_backend_cache() -> None:
    reset_backend_cache()
    yield
    reset_backend_cache()


def test_detect_priority_tmux_env(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    assert detect_backend() is BackendType.TMUX


def test_detect_priority_iterm2(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/bin/it2" if name == "it2" else None,
    )
    assert detect_backend() is BackendType.ITERM2


def test_detect_priority_path_tmux(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/tmux" if name == "tmux" else None,
    )
    assert detect_backend() is BackendType.TMUX


def test_detect_falls_back_to_inprocess(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert detect_backend() is BackendType.IN_PROCESS


@pytest.mark.asyncio
async def test_inprocess_spawn_wake_kill(tmp_path: Path) -> None:
    manager = TaskManager()
    backend = InProcessBackend(manager)

    class StubAgent:
        async def run_to_completion(self, conv, task, mode, cancel):
            await asyncio.sleep(0.05)
            return None

    class StubConv:
        pass

    request = SpawnRequest(
        team_name="demo",
        member_name="bob",
        agent_id="agent-bob",
        worktree_path=str(tmp_path),
        session_dir=str(tmp_path / "s"),
        agent_type="general-purpose",
        model="",
        initial_prompt="干活",
        plan_mode_required=False,
        agent=StubAgent(),
        conversation=StubConv(),
    )
    result = await backend.spawn(request)
    assert result.agent_id == "agent-bob"
    assert result.backend is BackendType.IN_PROCESS
    assert manager.get("agent-bob") is not None
    await asyncio.sleep(0.05)
    await backend.wake("", "agent-bob")
    await backend.kill("", "agent-bob")
    await asyncio.sleep(0.05)
    assert manager.get("agent-bob").status.terminal  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_tmux_spawn_argv(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"%5\n", b""

    async def fake_exec(*args: str, **kwargs: object) -> FakeProcess:
        captured["args"] = args
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    request = SpawnRequest(
        team_name="demo",
        member_name="alice",
        agent_id="agent-alice",
        worktree_path="/wt",
        session_dir="/s",
        agent_type="general-purpose",
        model="haiku",
        initial_prompt="任务",
        plan_mode_required=False,
    )
    backend = TmuxBackend()
    result = await backend.spawn(request)
    assert result.pane_id == "%5"
    args = captured["args"]
    assert isinstance(args, tuple)
    assert args[0] == "tmux"
    assert "split-window" in args
    assert "--team-member" in args
    assert "--agent-id" in args
    # initial prompt 不进命令行
    assert "任务" not in args


def test_teammate_visibility_rules() -> None:
    from pydantic import BaseModel

    from Arkcode.subagents.filter import (
        ALL_AGENT_DISALLOWED_TOOLS,
        RegistryPolicy,
        RegistryView,
    )
    from Arkcode.teams.spawner import TEAM_TOOL_NAMES
    from Arkcode.tools import Registry, Result, Tool

    class P(BaseModel):
        pass

    class Stub(Tool[P]):
        read_only = True
        params_model = P

        def __init__(self, name: str) -> None:
            self._name = name

        def name(self) -> str:
            return self._name

        def description(self) -> str:
            return self._name

        async def execute(self, params: P) -> Result:
            return Result("ok")

    parent = Registry()
    for name in (
        "Agent",
        "TaskCreate",
        "TaskGet",
        "TaskList",
        "TaskUpdate",
        "SendMessage",
        "read_file",
        "bash",
    ):
        parent.register(Stub(name))
    policy = RegistryPolicy(
        globally_denied=frozenset(),
        allowed=frozenset(TEAM_TOOL_NAMES | {"Agent"}),
        denied=frozenset({"write_file"}),
        keep_agent_schema=True,
    )
    view = RegistryView.from_parent(parent, policy, copy_discovery=False)
    names = {definition.name for definition in view.definitions()}
    assert {"TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "SendMessage"} <= names
    assert "Agent" in names
    assert ALL_AGENT_DISALLOWED_TOOLS == frozenset({"Agent"})
