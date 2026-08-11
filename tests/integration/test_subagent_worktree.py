"""SubAgent + Worktree 集成：隔离执行、生命周期与保留语义。"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Arkcode.agents.identity import AgentIdentity
from Arkcode.agents.parent import ParentContext
from Arkcode.conversations import Conversation
from Arkcode.llm import Request, StreamEnd, StreamEvent, TextDelta, ToolCallComplete
from Arkcode.subagents.approvals import ApprovalBroker
from Arkcode.subagents.catalog import Catalog
from Arkcode.subagents.launcher import SubAgentLauncher
from Arkcode.subagents.manager import TaskManager
from Arkcode.subagents.models import (
    Definition,
    JobStatus,
    LaunchRequest,
    Source,
)
from Arkcode.tools import new_default_registry
from Arkcode.worktrees import WorktreeManager
from Arkcode.worktrees.integration import WorktreeEnvironmentPreparer


class WorktreeProvider:
    """第一轮调用 write_file 写入相对路径，随后完成。"""

    name = "fake"
    model = "fake-model"

    def __init__(self, *, write: bool = True) -> None:
        self.write = write
        self.requests: list[Request] = []
        self.call_count = 0

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        self.call_count += 1
        if self.write and self.call_count == 1:
            yield ToolCallComplete(
                tool_id="w1",
                tool_name="write_file",
                arguments={"path": "hello.txt", "content": "hi"},
            )
            yield StreamEnd("tool_use")
            return
        yield TextDelta("完成")
        yield StreamEnd("end")


def worktree_definition() -> Definition:
    return Definition(
        name="worker",
        description="worktree 隔离角色",
        instructions_content="你在隔离副本中工作",
        isolation="worktree",
        max_turns=5,
        source=Source.BUILTIN,
    )


def parent_context(git_repo, provider: WorktreeProvider) -> ParentContext:
    conversation = Conversation()
    conversation.add_user("父历史")
    return ParentContext(
        workspace=git_repo,
        conversation=conversation,
        identity=AgentIdentity.main(str(git_repo)),
        registry=new_default_registry(),
        provider=provider,  # type: ignore[arg-type]
    )


async def build_launcher(
    git_repo: Path,
) -> tuple[SubAgentLauncher, TaskManager, WorktreeManager]:
    manager = await WorktreeManager.open(git_repo)
    task_manager = TaskManager()
    catalog = Catalog(project_root=git_repo, user_root=git_repo)
    catalog._definitions["worker"] = worktree_definition()  # type: ignore[attr-defined]
    launcher = SubAgentLauncher(
        catalog=catalog,
        task_manager=task_manager,
        broker=ApprovalBroker(),
        engine=None,
        version="test",
        workspace=git_repo,
        enable_background=True,
        worktree_preparer_factory=lambda: WorktreeEnvironmentPreparer(manager),
    )
    return launcher, task_manager, manager


@pytest.mark.asyncio
async def test_worktree_background_lifecycle_and_isolation(git_repo: Path) -> None:
    provider = WorktreeProvider(write=True)
    launcher, task_manager, _ = await build_launcher(git_repo)
    outcome = await launcher.launch(
        LaunchRequest(
            prompt="在 worktree 里写 hello.txt",
            description="隔离任务",
            subagent_type="worker",
            model=None,
            run_in_background=True,
            name="wt1",
        ),
        parent_context(git_repo, provider),
    )
    assert outcome.status == "async_launched"
    job = task_manager.get(outcome.job_id)
    assert job is not None
    assert job.status is JobStatus.PREPARING

    queue = task_manager.subscribe_done()
    job_id = await asyncio.wait_for(queue.get(), 10.0)
    assert job_id == outcome.job_id
    assert job.status is JobStatus.COMPLETED
    assert job.worktree_name.startswith("agent-a")
    assert not (git_repo / "hello.txt").exists()
    assert "Worktree 保留在" in job.result
    assert job.worktree_path
    assert (Path(job.worktree_path) / "hello.txt").read_text(encoding="utf-8") == "hi"


@pytest.mark.asyncio
async def test_clean_worktree_is_removed_after_run(git_repo: Path) -> None:
    provider = WorktreeProvider(write=False)
    launcher, task_manager, _ = await build_launcher(git_repo)
    outcome = await launcher.launch(
        LaunchRequest(
            prompt="只读任务",
            description="只读",
            subagent_type="worker",
            model=None,
            run_in_background=True,
            name="wt2",
        ),
        parent_context(git_repo, provider),
    )
    queue = task_manager.subscribe_done()
    await asyncio.wait_for(queue.get(), 10.0)
    job = task_manager.get(outcome.job_id)
    assert job is not None
    assert job.status is JobStatus.COMPLETED
    assert "Worktree 保留在" not in job.result
    assert not (git_repo / ".Arkcode" / "worktrees" / job.worktree_name).exists()


@pytest.mark.asyncio
async def test_worktree_job_cancel_terminates(git_repo: Path) -> None:
    provider = WorktreeProvider(write=True)
    launcher, task_manager, _ = await build_launcher(git_repo)
    outcome = await launcher.launch(
        LaunchRequest(
            prompt="慢任务",
            description="慢",
            subagent_type="worker",
            model=None,
            run_in_background=True,
            name="wt3",
        ),
        parent_context(git_repo, provider),
    )
    job = task_manager.get(outcome.job_id)
    assert job is not None
    await asyncio.sleep(0.05)
    assert await task_manager.stop(outcome.job_id) is True
    queue = task_manager.subscribe_done()
    await asyncio.wait_for(queue.get(), 10.0)
    assert job.status in {JobStatus.CANCELLED, JobStatus.FAILED}
    assert job.result
