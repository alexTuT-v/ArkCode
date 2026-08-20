"""Agent 与 Job 工具测试。"""

import asyncio
import json

import pytest

from Arkcode.agents.parent import parent_scope
from Arkcode.conversations import Conversation
from Arkcode.subagents.manager import TaskManager
from Arkcode.subagents.notification import format_task_notification
from Arkcode.subagents.tools import (
    AgentParams,
    AgentTool,
    JobGetTool,
    JobListTool,
    JobSendTool,
    JobStopTool,
)

from .test_launcher import FakeProvider, _definition, make_launcher, parent_context


def make_tool(tmp_path, *, enable_background: bool = True) -> AgentTool:
    launcher, _ = make_launcher(tmp_path, enable_background=enable_background)
    return AgentTool(launcher)


async def run_agent(tool: AgentTool, tmp_path, **params: object) -> str:
    context = parent_context(tmp_path, FakeProvider())
    with parent_scope(context):
        result = await tool.execute(AgentParams.model_validate(params))
    return result.content


@pytest.mark.asyncio
async def test_agent_tool_unknown_type_error(tmp_path) -> None:
    tool = make_tool(tmp_path)
    tool._launcher._catalog._definitions.update(  # type: ignore[attr-defined]
        {"explore": _definition(), "plan": _definition()}
    )
    content = await run_agent(
        tool,
        tmp_path,
        prompt="p",
        description="d",
        subagent_type="ghost",
    )
    assert content == "未知 subagent_type: ghost。可用类型: explore, plan"


@pytest.mark.asyncio
async def test_agent_tool_explore_returns_final_text(tmp_path) -> None:
    tool = make_tool(tmp_path)
    tool._launcher._catalog._definitions["explore"] = _definition()  # type: ignore[attr-defined]
    content = await run_agent(
        tool,
        tmp_path,
        prompt="去探索",
        description="探索",
        subagent_type="explore",
    )
    assert content == "完成"


@pytest.mark.asyncio
async def test_agent_tool_background_returns_async_launched(tmp_path) -> None:
    tool = make_tool(tmp_path)
    tool._launcher._catalog._definitions["explore"] = _definition()  # type: ignore[attr-defined]
    content = await run_agent(
        tool,
        tmp_path,
        prompt="后台",
        description="后台任务",
        subagent_type="explore",
        run_in_background=True,
    )
    payload = json.loads(content)
    assert payload["status"] == "async_launched"
    assert payload["job_id"].startswith("job-")


@pytest.mark.asyncio
async def test_agent_tool_fork_forces_background(tmp_path) -> None:
    tool = make_tool(tmp_path)
    content = await run_agent(
        tool,
        tmp_path,
        prompt="fork 任务",
        description="fork",
        subagent_type=None,
        run_in_background=False,
    )
    payload = json.loads(content)
    assert payload["status"] == "async_launched"


@pytest.mark.asyncio
async def test_agent_tool_fork_blocked_when_background_disabled(tmp_path) -> None:
    content = await run_agent(
        make_tool(tmp_path, enable_background=False),
        tmp_path,
        prompt="fork",
        description="fork",
        subagent_type=None,
    )
    assert "后台禁用，无法 Fork" in content


@pytest.mark.asyncio
async def test_agent_schema_is_stable(tmp_path) -> None:
    schema = AgentTool(make_launcher(tmp_path)[0]).get_schema()
    params = schema["input_schema"]["properties"]
    assert "prompt" in params
    assert "description" in params
    assert "subagent_type" in params
    assert "team_name" in params


@pytest.mark.asyncio
async def test_job_tools_list_get_stop_send(tmp_path) -> None:
    manager = TaskManager()
    from Arkcode.subagents.models import BackgroundTask

    from .test_manager import StubAgent

    job = BackgroundTask(
        id="job-abc",
        agent_id="agent-1",
        name="alice",
        agent_type="explore",
        agent=StubAgent(),  # type: ignore[arg-type]
        conversation=Conversation(),
        task_text="t",
        run_in_background=True,
    )
    manager.launch(job)
    queue = manager.subscribe_done()
    await asyncio.wait_for(queue.get(), 2.0)

    listed = await JobListTool(manager).execute(JobListTool.params_model())
    assert "job-abc" in listed.content
    assert "completed" in listed.content

    got = await JobGetTool(manager).execute(
        JobGetTool.params_model.model_validate({"job_id": "job-abc"})
    )
    assert '"job_id": "job-abc"' in got.content

    stopped = await JobStopTool(manager).execute(
        JobStopTool.params_model.model_validate({"job_id": "job-abc"})
    )
    assert json.loads(stopped.content)["status"] == "cancellation_requested"

    sent = await JobSendTool(manager).execute(
        JobSendTool.params_model.model_validate(
            {"name": "alice", "message": "继续"}
        )
    )
    payload = json.loads(sent.content)
    assert payload["status"] == "async_launched"
    assert payload["job_id"].startswith("job-")


def test_notification_format() -> None:
    from Arkcode.subagents.models import BackgroundTask

    from .test_manager import StubAgent

    job = BackgroundTask(
        id="job-x",
        agent_id="agent-1",
        name="alice",
        agent_type="explore",
        agent=StubAgent(),  # type: ignore[arg-type]
        conversation=Conversation(),
        task_text="t",
        run_in_background=True,
    )
    job.status = job.status.COMPLETED
    job.result = "搞定"
    text = format_task_notification(job)
    assert text.startswith("<task-notification>")
    assert "job-x" in text
    assert "alice" in text
    assert "completed" in text
    assert "搞定" in text
    assert "</task-notification>" in text
