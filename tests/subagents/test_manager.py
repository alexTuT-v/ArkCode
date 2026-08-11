"""TaskManager/BackgroundTask 状态机、转后台与续派测试。"""

import asyncio

import pytest

from Arkcode.agents.events import RunResult, RunStatus, Usage
from Arkcode.conversations import Conversation
from Arkcode.subagents.manager import TaskManager
from Arkcode.subagents.models import BackgroundTask, JobStatus


class StubAgent:
    def __init__(
        self,
        *,
        outcome: str = "completed",
        delay: float = 0.0,
    ) -> None:
        self.outcome = outcome
        self.delay = delay
        self.runs: list[tuple[str, object]] = []
        self.conversations: list[Conversation] = []

    async def run_to_completion(
        self,
        conv: Conversation,
        task: str,
        mode: object,
        cancel: asyncio.Event,
    ) -> RunResult:
        self.runs.append((task, mode))
        self.conversations.append(conv)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.outcome == "raise":
            raise ValueError("boom")
        if self.outcome == "cancel":
            raise asyncio.CancelledError()
        return RunResult(
            status=RunStatus.COMPLETED,
            final_text="结果文本",
            error=None,
            usage=Usage(),
            tool_count=3,
            last_activity="read_file",
        )


def make_job(
    agent: StubAgent,
    *,
    job_id: str = "job-1",
    name: str = "n",
    background: bool = True,
    delay: float = 0.0,
) -> BackgroundTask:
    return BackgroundTask(
        id=job_id,
        agent_id="agent-1",
        name=name,
        agent_type="explore",
        agent=agent,  # type: ignore[arg-type]
        conversation=Conversation(),
        task_text="初始任务",
        run_in_background=background,
    )


async def wait_done(manager: TaskManager) -> str:
    queue = manager.subscribe_done()
    return await asyncio.wait_for(queue.get(), 2.0)


@pytest.mark.asyncio
async def test_job_completed_pushes_done_once() -> None:
    manager = TaskManager()
    agent = StubAgent()
    job = make_job(agent)
    manager.launch(job)

    job_id = await wait_done(manager)
    assert job_id == job.id
    assert job.status is JobStatus.COMPLETED
    assert job.result == "结果文本"
    assert job.tool_count == 3
    queue = manager.subscribe_done()
    assert queue.empty()


@pytest.mark.asyncio
async def test_job_exception_becomes_failed() -> None:
    manager = TaskManager()
    job = make_job(StubAgent(outcome="raise"))
    manager.launch(job)
    await wait_done(manager)
    assert job.status is JobStatus.FAILED
    assert "boom" in job.result


@pytest.mark.asyncio
async def test_job_cancelled_by_stop() -> None:
    manager = TaskManager()
    agent = StubAgent(delay=0.3)
    job = make_job(agent, delay=0.3)
    manager.launch(job)
    await asyncio.sleep(0.05)
    assert await manager.stop(job.id) is True
    await wait_done(manager)
    assert job.status is JobStatus.CANCELLED
    assert await manager.stop(job.id) is False


@pytest.mark.asyncio
async def test_foreground_timeout_moves_to_background_same_task() -> None:
    manager = TaskManager()
    agent = StubAgent(delay=0.4)
    job = make_job(agent, background=False, delay=0.4)
    manager.launch(job)
    task_identity = id(job.task)
    conversation = job.conversation

    result = await manager.wait_foreground(job.id, timeout=0.05)
    assert result is None
    assert not job.backgrounded_event.is_set()
    assert manager.move_foreground_to_background() == job.id
    assert job.run_in_background is True
    assert id(job.task) == task_identity
    assert job.conversation is conversation

    await wait_done(manager)
    assert job.status is JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_foreground_returns_run_result_on_completion() -> None:
    manager = TaskManager()
    job = make_job(StubAgent(), background=False)
    manager.launch(job)
    result = await manager.wait_foreground(job.id, timeout=2.0)
    assert result is not None
    assert result.final_text == "结果文本"


@pytest.mark.asyncio
async def test_resume_reuses_agent_and_conversation() -> None:
    manager = TaskManager()
    agent = StubAgent()
    job = make_job(agent)
    manager.launch(job)
    await wait_done(manager)

    resumed = manager.resume("n", "续派任务")
    assert resumed.id != job.id
    assert resumed.agent is agent
    assert resumed.conversation is job.conversation
    assert resumed.run_in_background is True
    await wait_done(manager)
    assert resumed.status is JobStatus.COMPLETED
    assert agent.runs[-1][0] == "续派任务"


@pytest.mark.asyncio
async def test_resume_rejects_running_agent() -> None:
    manager = TaskManager()
    job = make_job(StubAgent(delay=0.3), delay=0.3)
    manager.launch(job)
    await asyncio.sleep(0.05)
    with pytest.raises(RuntimeError):
        manager.resume("n", "重入")
    await manager.stop(job.id)
    await wait_done(manager)


@pytest.mark.asyncio
async def test_shutdown_cancels_all_jobs() -> None:
    manager = TaskManager()
    job = make_job(StubAgent(delay=1.0), delay=1.0)
    manager.launch(job)
    await manager.shutdown()
    assert job.status is JobStatus.CANCELLED
