"""ApprovalBroker、Fork 构造与 SubAgentLauncher 启动测试。"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from Arkcode.agents.events import ApprovalRequest
from Arkcode.agents.identity import AgentIdentity
from Arkcode.agents.parent import ParentContext
from Arkcode.conversations import Conversation
from Arkcode.llm import Request, StreamEnd, StreamEvent, TextDelta
from Arkcode.permissions import Outcome
from Arkcode.subagents.approvals import ApprovalBroker
from Arkcode.subagents.catalog import Catalog
from Arkcode.subagents.fork import (
    FORK_BOILERPLATE,
    AgentLaunchBlocked,
    assert_can_launch_agent,
    build_forked_messages,
)
from Arkcode.subagents.launcher import AgentToolError, SubAgentLauncher
from Arkcode.subagents.manager import TaskManager
from Arkcode.subagents.models import Definition, LaunchRequest, Source
from Arkcode.tools import Registry


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, text: str = "完成") -> None:
        self.text = text
        self.requests: list[Request] = []

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        yield TextDelta(self.text)
        yield StreamEnd("end")


def make_launcher(
    tmp_path,
    *,
    enable_background: bool = True,
    catalog: Catalog | None = None,
) -> tuple[SubAgentLauncher, TaskManager]:
    manager = TaskManager()
    broker = ApprovalBroker()
    launcher = SubAgentLauncher(
        catalog=catalog or Catalog(project_root=tmp_path, user_root=tmp_path),
        task_manager=manager,
        broker=broker,
        engine=None,
        version="test",
        workspace=tmp_path,
        enable_background=enable_background,
    )
    return launcher, manager


def parent_context(tmp_path, provider: FakeProvider) -> ParentContext:
    conversation = Conversation()
    conversation.add_user("父历史")
    return ParentContext(
        workspace=tmp_path,
        conversation=conversation,
        identity=AgentIdentity.main(str(tmp_path)),
        registry=Registry(),
        provider=provider,  # type: ignore[arg-type]
    )


def _definition() -> Definition:
    return Definition(
        name="explore",
        description="只读探索",
        instructions_content="你是探索者",
        disallowed_tools=("write_file", "edit_file"),
        max_turns=5,
        source=Source.BUILTIN,
    )


@pytest.mark.asyncio
async def test_broker_responds_only_matching_agent(tmp_path) -> None:
    broker = ApprovalBroker()
    loop = asyncio.get_running_loop()
    first = ApprovalRequest(
        "bash",
        "{}",
        "r1",
        loop.create_future(),
        agent_id="a1",
        agent_name="alice",
    )
    second = ApprovalRequest(
        "bash",
        "{}",
        "r2",
        loop.create_future(),
        agent_id="b1",
        agent_name="bob",
    )
    task_first = asyncio.create_task(broker.submit(first))
    task_second = asyncio.create_task(broker.submit(second))
    record_first = await broker.next()
    await broker.next()

    assert broker.respond(record_first.request_id, Outcome.ALLOW_ONCE)
    assert await asyncio.wait_for(task_first, 1.0) is Outcome.ALLOW_ONCE
    assert not task_second.done()

    broker.cancel_agent("b1")
    assert await asyncio.wait_for(task_second, 1.0) is Outcome.DENY_ONCE


def test_broker_cancel_agent_rejects_pending(tmp_path) -> None:
    async def run() -> None:
        broker = ApprovalBroker()
        loop = asyncio.get_running_loop()
        request = ApprovalRequest(
            "bash",
            "{}",
            "r",
            loop.create_future(),
            agent_id="a1",
            agent_name="alice",
        )
        task = asyncio.create_task(broker.submit(request))
        await broker.next()
        broker.cancel_agent("a1")
        assert await asyncio.wait_for(task, 1.0) is Outcome.DENY_ONCE

    asyncio.run(run())


def test_build_forked_messages_preserves_prefix_and_boilerplate() -> None:
    parent = Conversation()
    parent.add_user("父问题")
    parent.add_assistant("父回答")
    before = parent.messages()
    messages = build_forked_messages(parent, "子任务")

    assert messages[:2] == before
    first_user = messages[-1]
    assert first_user.role == "user"
    assert first_user.content.startswith(FORK_BOILERPLATE)
    assert "子任务" in first_user.content


def test_build_forked_messages_repairs_incomplete_tool_call() -> None:
    from Arkcode.llm import Message, ToolCall

    parent = Conversation.from_messages(
        [
            Message(role="user", content="u"),
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall("c1", "read_file", "{}")],
            ),
        ]
    )
    messages = build_forked_messages(parent, "任务")
    tool_message = messages[2]
    assert tool_message.role == "tool"
    assert tool_message.tool_results[0].tool_call_id == "c1"


def test_assert_can_launch_agent_blocks_fork_source_and_boilerplate() -> None:
    identity = AgentIdentity(
        agent_id="a1",
        parent_id="lead",
        trace_id="t",
        agent_type="fork",
        name="fork",
        source="fork",
    )
    with pytest.raises(AgentLaunchBlocked):
        assert_can_launch_agent(identity, [])
    history = build_forked_messages(Conversation(), "任务")
    main = AgentIdentity.main()
    with pytest.raises(AgentLaunchBlocked):
        assert_can_launch_agent(main, history)


@pytest.mark.asyncio
async def test_launcher_defined_runs_from_empty_conversation(tmp_path) -> None:
    provider = FakeProvider()
    parent = parent_context(tmp_path, provider)
    launcher, manager = make_launcher(tmp_path)
    launcher._catalog._definitions["explore"] = _definition()  # type: ignore[attr-defined]
    outcome = await launcher.launch(
        LaunchRequest(
            prompt="调查",
            description="调查任务",
            subagent_type="explore",
            model=None,
            run_in_background=False,
            name="e1",
        ),
        parent,
    )
    assert outcome.status == "completed"
    assert outcome.final_text == "完成"
    assert provider.requests
    assert provider.requests[0].system.stable.endswith("你是探索者")


@pytest.mark.asyncio
async def test_launcher_unknown_type_raises(tmp_path) -> None:
    launcher, _ = make_launcher(tmp_path)
    with pytest.raises(AgentToolError):
        await launcher.launch(
            LaunchRequest(
                prompt="x",
                description="x",
                subagent_type="ghost",
                model=None,
                run_in_background=False,
                name=None,
            ),
            parent_context(tmp_path, FakeProvider()),
        )


@pytest.mark.asyncio
async def test_launcher_fork_keeps_parent_prefix(tmp_path) -> None:
    provider = FakeProvider()
    parent = parent_context(tmp_path, provider)
    launcher, manager = make_launcher(tmp_path)
    outcome = await launcher.launch(
        LaunchRequest(
            prompt="子任务",
            description="fork",
            subagent_type=None,
            model=None,
            run_in_background=False,
            name="fork1",
        ),
        parent,
    )
    assert outcome.status == "async_launched"
    job = manager.get(outcome.job_id)
    assert job is not None
    assert job.conversation.messages()[0].content == "父历史"


@pytest.mark.asyncio
async def test_launcher_background_disabled_fork_raises(tmp_path) -> None:
    launcher, _ = make_launcher(tmp_path, enable_background=False)
    with pytest.raises(AgentToolError):
        await launcher.launch(
            LaunchRequest(
                prompt="x",
                description="x",
                subagent_type=None,
                model=None,
                run_in_background=True,
                name=None,
            ),
            parent_context(tmp_path, FakeProvider()),
        )


@pytest.mark.asyncio
async def test_launcher_background_returns_async_launched(tmp_path) -> None:
    provider = FakeProvider()
    launcher, manager = make_launcher(tmp_path)
    launcher._catalog._definitions["explore"] = _definition()  # type: ignore[attr-defined]
    outcome = await launcher.launch(
        LaunchRequest(
            prompt="后台任务",
            description="后台",
            subagent_type="explore",
            model=None,
            run_in_background=True,
            name="bg1",
        ),
        parent_context(tmp_path, provider),
    )
    assert outcome.status == "async_launched"
    queue = manager.subscribe_done()
    job_id = await asyncio.wait_for(queue.get(), 2.0)
    assert job_id == outcome.job_id
