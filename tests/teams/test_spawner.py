"""TeamSpawner 预注册顺序与失败回滚测试。"""

import json
from pathlib import Path

import pytest

from Arkcode.agents.identity import AgentIdentity
from Arkcode.agents.parent import ParentContext
from Arkcode.conversations import Conversation
from Arkcode.subagents.approvals import ApprovalBroker
from Arkcode.subagents.catalog import Catalog
from Arkcode.subagents.launcher import SubAgentLauncher
from Arkcode.subagents.manager import TaskManager
from Arkcode.subagents.models import Definition, LaunchRequest, Source
from Arkcode.teams.mailbox import Box
from Arkcode.teams.manager import TeamManager
from Arkcode.teams.models import BackendType, SpawnResult
from Arkcode.teams.spawner import TeamSpawner
from Arkcode.tools import new_default_registry
from Arkcode.worktrees import WorktreeManager


class FakeProvider:
    name = "fake"
    model = "fake"

    async def stream(self, req):
        yield


class MockBackend:
    def __init__(self) -> None:
        self.spawn_calls: list[object] = []
        self.fail = False
        self.pane_id = "%42"

    def type(self) -> BackendType:
        return BackendType.TMUX

    async def spawn(self, request):
        self.spawn_calls.append(request)
        if self.fail:
            raise RuntimeError("spawn 失败")
        return SpawnResult(
            pane_id=self.pane_id,
            agent_id=request.agent_id,
            backend=BackendType.TMUX,
        )

    async def wake(self, pane_id, agent_id):
        return None

    async def kill(self, pane_id, agent_id):
        return None

    async def is_alive(self, pane_id, agent_id):
        return True


def parent_context(git_repo: Path) -> ParentContext:
    return ParentContext(
        workspace=git_repo,
        conversation=Conversation(),
        identity=AgentIdentity.main(str(git_repo)),
        registry=new_default_registry(),
        provider=FakeProvider(),  # type: ignore[arg-type]
    )


def _definition() -> Definition:
    return Definition(
        name="general-purpose",
        description="通用",
        instructions_content="你是队员",
        max_turns=5,
        source=Source.BUILTIN,
    )


@pytest.mark.asyncio
async def test_spawn_order_preegisters_member(git_repo: Path) -> None:
    wt_mgr = await WorktreeManager.open(git_repo)
    task_mgr = TaskManager()
    catalog = Catalog(project_root=git_repo, user_root=git_repo)
    catalog._definitions["general-purpose"] = _definition()  # type: ignore[attr-defined]
    launcher = SubAgentLauncher(
        catalog=catalog,
        task_manager=task_mgr,
        broker=ApprovalBroker(),
        engine=None,
        version="test",
        workspace=git_repo,
    )
    team_manager = TeamManager(git_repo.parent, wt_mgr=wt_mgr, task_mgr=task_mgr)
    team = await team_manager.create("demo")
    team.backend = BackendType.TMUX
    backend = MockBackend()
    spawner = TeamSpawner(
        team_manager=team_manager,
        worktree_manager=wt_mgr,
        launcher=launcher,
        session_root=git_repo / ".Arkcode" / "sessions",
        backend_factory=lambda backend_type: backend,
    )

    result = await spawner.spawn(
        LaunchRequest(
            prompt="写 hello",
            description="任务",
            subagent_type=None,
            model=None,
            run_in_background=False,
            name="alice",
            team_name="demo",
        ),
        parent_context(git_repo),
    )
    payload = json.loads(result.content)
    assert payload["member_name"] == "alice"
    assert payload["pane_id"] == "%42"
    # spawn 入口时 config 已能看到最终 member/agent_id
    request = backend.spawn_calls[0]
    assert request.agent_id == payload["agent_id"]
    team_reloaded = json.loads(
        (git_repo.parent / ".Arkcode" / "teams" / "demo" / "config.json").read_text(
            encoding="utf-8"
        )
    )
    assert team_reloaded["members"][0]["name"] == "alice"
    assert team_reloaded["members"][0]["pane_id"] == "%42"
    # Pane 初始 prompt 在 spawn 前写入 mailbox
    box = Box(team.config_dir)
    messages = await box.read(payload["agent_id"])
    assert any(message.text == "写 hello" for message in messages)


@pytest.mark.asyncio
async def test_spawn_failure_rolls_back(git_repo: Path) -> None:
    wt_mgr = await WorktreeManager.open(git_repo)
    task_mgr = TaskManager()
    catalog = Catalog(project_root=git_repo, user_root=git_repo)
    catalog._definitions["general-purpose"] = _definition()  # type: ignore[attr-defined]
    launcher = SubAgentLauncher(
        catalog=catalog,
        task_manager=task_mgr,
        broker=ApprovalBroker(),
        engine=None,
        version="test",
        workspace=git_repo,
    )
    team_manager = TeamManager(git_repo.parent, wt_mgr=wt_mgr, task_mgr=task_mgr)
    team = await team_manager.create("demo")
    team.backend = BackendType.TMUX
    backend = MockBackend()
    backend.fail = True
    spawner = TeamSpawner(
        team_manager=team_manager,
        worktree_manager=wt_mgr,
        launcher=launcher,
        session_root=git_repo / ".Arkcode" / "sessions",
        backend_factory=lambda backend_type: backend,
    )
    with pytest.raises(RuntimeError):
        await spawner.spawn(
            LaunchRequest(
                prompt="x",
                description="x",
                subagent_type=None,
                model=None,
                run_in_background=False,
                name="alice",
                team_name="demo",
            ),
            parent_context(git_repo),
        )
    team_reloaded = json.loads(
        (git_repo.parent / ".Arkcode" / "teams" / "demo" / "config.json").read_text(
            encoding="utf-8"
        )
    )
    assert team_reloaded["members"] == []
    assert team_manager.name_registry.resolve("alice") is None
    assert not list((git_repo / ".Arkcode" / "worktrees").glob("team-demo*"))
