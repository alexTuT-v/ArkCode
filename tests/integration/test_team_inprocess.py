"""in-process Team 端到端：创建 → spawn → idle → 续派。"""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Arkcode.agents.identity import AgentIdentity
from Arkcode.agents.parent import ParentContext
from Arkcode.conversations import Conversation
from Arkcode.llm import Request, StreamEnd, StreamEvent, TextDelta
from Arkcode.subagents.approvals import ApprovalBroker
from Arkcode.subagents.catalog import Catalog
from Arkcode.subagents.launcher import SubAgentLauncher
from Arkcode.subagents.manager import TaskManager
from Arkcode.subagents.models import Definition, LaunchRequest, Source
from Arkcode.teams.backends.inprocess import InProcessBackend
from Arkcode.teams.mailbox import Box
from Arkcode.teams.manager import TeamManager
from Arkcode.teams.models import BackendType
from Arkcode.teams.spawner import TeamSpawner
from Arkcode.tools import new_default_registry
from Arkcode.worktrees import WorktreeManager


class TeamProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.requests: list[Request] = []

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        yield TextDelta("bob 完成任务")
        yield StreamEnd("end")


def _definition() -> Definition:
    return Definition(
        name="general-purpose",
        description="通用队员",
        instructions_content="你是队员",
        max_turns=5,
        source=Source.BUILTIN,
    )


@pytest.mark.asyncio
async def test_inprocess_team_create_spawn_idle_resume(git_repo: Path) -> None:
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
    team = await team_manager.create("inproc")
    team.backend = BackendType.IN_PROCESS
    spawner = TeamSpawner(
        team_manager=team_manager,
        worktree_manager=wt_mgr,
        launcher=launcher,
        session_root=git_repo / ".Arkcode" / "sessions",
        backend_factory=lambda backend_type: InProcessBackend(task_mgr),
    )
    provider = TeamProvider()
    parent = ParentContext(
        workspace=git_repo,
        conversation=Conversation(),
        identity=AgentIdentity.main(str(git_repo)),
        registry=new_default_registry(),
        provider=provider,  # type: ignore[arg-type]
    )
    before_cwd = Path.cwd()
    result = await spawner.spawn(
        LaunchRequest(
            prompt="在 worktree 里完成任务",
            description="任务",
            subagent_type="general-purpose",
            model=None,
            run_in_background=False,
            name="bob",
            team_name="inproc",
        ),
        parent,
    )
    payload = json.loads(result.content)
    assert payload["member_name"] == "bob"
    assert payload["backend"] == "in-process"

    queue = task_mgr.subscribe_done()
    first_job_id = await asyncio.wait_for(queue.get(), 10.0)
    assert first_job_id == payload["agent_id"]
    await asyncio.sleep(0.1)

    # idle 状态与 Lead mailbox
    team_reloaded = json.loads(
        (git_repo.parent / ".Arkcode" / "teams" / "inproc" / "config.json").read_text(
            encoding="utf-8"
        )
    )
    assert team_reloaded["members"][0]["is_active"] is False
    box = Box(team.config_dir)
    lead_messages = await box.read("lead")
    assert any("[idle] bob" in message.text for message in lead_messages)
    assert Path.cwd() == before_cwd

    # 续派：从已完成 Job 复用 Agent/Conversation
    await team_manager.set_member_active("inproc", "bob", True)
    resumed = task_mgr.resume("bob", "再做一件事")
    second_job_id = await asyncio.wait_for(queue.get(), 10.0)
    assert second_job_id == resumed.id
    await asyncio.sleep(0.1)
    assert resumed.status.value in {"completed", "failed"}
