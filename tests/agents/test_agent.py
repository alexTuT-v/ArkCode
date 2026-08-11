"""Agent ReAct 循环、停止条件与并发策略测试。"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from Arkcode.agents import (
    MAX_ITERATIONS,
    MAX_UNKNOWN_RUN,
    NOTICE_CANCELLED,
    NOTICE_MAX_ITER,
    NOTICE_STREAM_ERR,
    NOTICE_UNKNOWN_TOOLS,
    Agent,
    CompactPhase,
    Mode,
    Phase,
)
from Arkcode.agents.events import RunStatus
from Arkcode.agents.runtime import SessionRuntime
from Arkcode.context import (
    CompactCircuitBreaker,
    RecoveryState,
    new_session_context,
)
from Arkcode.conversations import Conversation
from Arkcode.llm import (
    Message,
    PromptTooLongError,
    Request,
    StreamEnd,
    StreamError,
    StreamEvent,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCall,
    ToolCallComplete,
    ToolDefinition,
)
from Arkcode.memory import MemoryTurn
from Arkcode.permissions import Decision, Outcome, new_engine
from Arkcode.prompts import combine_reminders, deferred_tools_reminder, plan_reminder
from Arkcode.sessions.journal import SessionJournal
from Arkcode.tools import Registry, Result
from Arkcode.tools.base import Tool
from Arkcode.tools.builtins.tool_search import ToolSearchTool


class RecordingSink:
    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.boundaries: list[object] = []

    def append_message(self, message: Message) -> None:
        self.messages.append(message)

    def append_boundary(self, boundary: object) -> None:
        self.boundaries.append(boundary)


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.call_count = 0
        self.received: list[tuple[list[Message], list[ToolDefinition], str]] = []
        self.requests: list[Request] = []

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        self.received.append((req.messages, req.tools, req.reminder))
        script = self.scripts[self.call_count]
        self.call_count += 1
        for event in script:
            yield event


class RepeatingToolProvider(FakeProvider):
    def __init__(self, tool_name: str = "read_file") -> None:
        super().__init__([])
        self.tool_name = tool_name

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        self.received.append((req.messages, req.tools, req.reminder))
        self.call_count += 1
        yield ToolCallComplete(
            tool_id=f"call-{self.call_count}",
            tool_name=self.tool_name,
            arguments={},
        )
        yield end()


class BlockingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__([])
        self.started = asyncio.Event()
        self.closed = asyncio.Event()

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        self.received.append((req.messages, req.tools, req.reminder))
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.closed.set()
        yield end()


class LongSessionProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.main_calls = 0
        self.summary_calls = 0

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        if req.tools is None:
            self.summary_calls += 1
            yield TextDelta("<summary>long session summary</summary>")
            yield end()
            return
        self.main_calls += 1
        if self.main_calls < MAX_ITERATIONS:
            yield ToolCallComplete(
                tool_id=f"large-{self.main_calls}",
                tool_name="large_read",
                arguments={},
            )
        else:
            yield TextDelta("long session complete")
        yield end(self.main_calls * 10000, 20)


@dataclass
class Tracker:
    active: int = 0
    peak: int = 0
    starts: list[str] = field(default_factory=list)
    ends: list[str] = field(default_factory=list)


class InstrumentedParams(BaseModel):
    label: str | None = None


@dataclass
class InstrumentedTool(Tool[InstrumentedParams]):
    tool_name: str
    _read_only: bool = False
    delay: float = 0
    tracker: Tracker | None = None
    params_model = InstrumentedParams

    @property
    def read_only(self) -> bool:
        return self._read_only

    def name(self) -> str:
        return self.tool_name

    def description(self) -> str:
        return self.tool_name

    async def execute(self, params: InstrumentedParams) -> Result:
        label = params.label or self.tool_name
        if self.tracker is not None:
            self.tracker.active += 1
            self.tracker.peak = max(self.tracker.peak, self.tracker.active)
            self.tracker.starts.append(label)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            return Result(label)
        finally:
            if self.tracker is not None:
                self.tracker.ends.append(label)
                self.tracker.active -= 1


class LargeResultTool(InstrumentedTool):
    async def execute(self, params: InstrumentedParams) -> Result:
        return Result("x" * 30000)


class ActivatingSkillTool(InstrumentedTool):
    def __init__(self) -> None:
        super().__init__("LoadSkill", True)
        self.agent: Agent | None = None

    async def execute(self, params: InstrumentedParams) -> Result:
        assert self.agent is not None
        self.agent.activate_skill("review", "Check every bug")
        return Result("activated")


def registry_with(*tools: InstrumentedTool) -> Registry:
    registry = Registry()
    for tool in tools:
        registry.register(tool)
    return registry


def call(call_id: str, name: str, label: str = "") -> ToolCall:
    return ToolCall(
        id=call_id,
        name=name,
        input=json.dumps({"label": label}) if label else "{}",
    )


def complete(call: ToolCall) -> ToolCallComplete:
    return ToolCallComplete(call.id, call.name, json.loads(call.input))


def end(input_tokens: int = 0, output_tokens: int = 0) -> StreamEnd:
    return StreamEnd("tool_use", input_tokens, output_tokens)


async def collect(
    agent: Agent,
    conversation: Conversation,
    *,
    mode: Mode = Mode.NORMAL,
    cancel: asyncio.Event | None = None,
) -> list[Any]:
    return [
        event
        async for event in agent.run(
            conversation,
            mode,
            cancel or asyncio.Event(),
        )
    ]


@pytest.mark.asyncio
async def test_run_to_completion_appends_task_and_returns_result(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        [
            [TextDelta("探索完成"), end()],
        ]
    )
    session_runtime = runtime(tmp_path)
    conversation = Conversation()
    conversation.add_user("原有问题")
    agent = Agent(
        provider,
        Registry(),
        "test",
        None,
        runtime=session_runtime,
        instructions_content="你是只读探索者",
    )
    result = await agent.run_to_completion(conversation, "去读 README")
    assert result.status is RunStatus.COMPLETED
    assert result.final_text == "探索完成"
    assert conversation.messages()[-1].role == "assistant"
    assert provider.requests[0].system.stable.endswith("你是只读探索者")


@pytest.mark.asyncio
async def test_run_to_completion_max_turns_returns_limit_reached(
    tmp_path: Path,
) -> None:
    provider = RepeatingToolProvider("read_file")
    session_runtime = runtime(tmp_path)
    conversation = Conversation()
    agent = Agent(
        provider,
        registry_with(InstrumentedTool("read_file", _read_only=True)),
        "test",
        None,
        runtime=session_runtime,
        max_turns=2,
    )
    result = await agent.run_to_completion(conversation, "循环任务")
    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error is None


class MemorySpy:
    def __init__(self) -> None:
        self.turns: list[MemoryTurn] = []
        self.recall_queries: list[str] = []
        self.consolidation_calls = 0
        self.recall_text = ""

    def load_index(self) -> str:
        return "fresh memory"

    async def recall(self, query: str) -> str:
        self.recall_queries.append(query)
        return self.recall_text

    def schedule_extract(self, turn: MemoryTurn) -> None:
        self.turns.append(turn)

    def schedule_consolidation(self) -> None:
        self.consolidation_calls += 1


@pytest.mark.asyncio
async def test_agent_injects_context_and_schedules_memory_update(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([[TextDelta("好的"), end()]])
    session_runtime = runtime(tmp_path)
    memory = MemorySpy()
    conversation = Conversation()
    conversation.add_user("请记住我喜欢简洁回复")
    agent = Agent(
        provider,
        Registry(),
        runtime=session_runtime,
        memory_manager=memory,  # type: ignore[arg-type]
        instruction_text="project instruction",
        memory_text="old memory",
    )

    await collect(agent, conversation)
    assert len(memory.turns) == 1
    assert memory.turns[0].session_id == session_runtime.session.session_id
    assert memory.turns[0].user_text == "请记住我喜欢简洁回复"
    assert memory.turns[0].assistant_text == "好的"
    assert memory.consolidation_calls == 1
    stable = provider.requests[0].system.stable
    assert "project instruction" in stable
    assert "fresh memory" in stable


@pytest.mark.asyncio
async def test_agent_injects_recalled_memory_without_persisting_it(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([[TextDelta("回答"), end()]])
    memory = MemorySpy()
    memory.recall_text = "<system-reminder>unique recalled memory</system-reminder>"
    conversation = Conversation()
    conversation.add_user("当前问题")

    await collect(
        Agent(
            provider,
            Registry(),
            runtime=runtime(tmp_path),
            memory_manager=memory,  # type: ignore[arg-type]
        ),
        conversation,
    )

    assert memory.recall_queries == ["当前问题"]
    assert "unique recalled memory" in provider.requests[0].reminder
    assert all(
        "unique recalled memory" not in message.content
        for message in conversation.messages()
    )


@pytest.mark.asyncio
async def test_agent_rebuilds_skill_environment_between_iterations(
    tmp_path: Path,
) -> None:
    tool_call = call("skill-1", "LoadSkill")
    provider = FakeProvider(
        [
            [complete(tool_call), end()],
            [TextDelta("done"), end()],
        ]
    )
    tool = ActivatingSkillTool()
    registry = Registry()
    registry.register(tool)
    conversation = Conversation()
    conversation.add_user("review this")
    agent = Agent(provider, registry, runtime=runtime(tmp_path))
    tool.agent = agent
    agent.set_skill_catalog("## Available Skills\n\n- review: Review code")

    await collect(agent, conversation)

    first = provider.requests[0].system
    second = provider.requests[1].system
    assert "Available Skills" in first.environment
    assert "Check every bug" not in first.environment
    assert "## Active Skills" in second.environment
    assert "Check every bug" in second.environment
    assert "Check every bug" not in second.stable


@pytest.mark.asyncio
async def test_load_skill_is_read_only_without_permission_approval(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        [
            [complete(call("skill-1", "LoadSkill")), end()],
            [TextDelta("done"), end()],
        ]
    )
    tool = ActivatingSkillTool()
    registry = Registry()
    registry.register(tool)
    conversation = Conversation()
    conversation.add_user("review")
    engine, error = new_engine(str(tmp_path))
    assert error is None
    agent = Agent(provider, registry, engine=engine, runtime=runtime(tmp_path))
    tool.agent = agent

    events = await collect(agent, conversation)

    assert not [event for event in events if event.approval is not None]
    assert agent.active_skills == {"review": "Check every bug"}


def test_agent_reactivates_and_clears_skills_without_changing_catalog() -> None:
    agent = Agent(FakeProvider([]), Registry())
    agent.set_skill_catalog("catalog")
    agent.activate_skill("review", "v1")
    agent.activate_skill("commit", "commit")
    agent.activate_skill("review", "v2")

    assert agent.active_skills == {"review": "v2", "commit": "commit"}

    agent.clear_active_skills()

    assert agent.active_skills == {}
    assert agent._skill_catalog == "catalog"


@pytest.mark.asyncio
async def test_agent_schedules_memory_update_every_natural_turn(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([[TextDelta("done"), end()]])
    session_runtime = runtime(tmp_path)
    memory = MemorySpy()
    conversation = Conversation.from_messages(
        [Message(role="user", content="普通消息")]
    )

    await collect(
        Agent(
            provider,
            Registry(),
            runtime=session_runtime,
            memory_manager=memory,  # type: ignore[arg-type]
        ),
        conversation,
    )

    assert len(memory.turns) == 1


@pytest.mark.asyncio
async def test_agent_does_not_extract_empty_final_even_with_memory_signal(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([[end()]])
    memory = MemorySpy()
    conversation = Conversation.from_messages(
        [Message(role="user", content="请记住这件事")]
    )

    await collect(
        Agent(
            provider,
            Registry(),
            runtime=runtime(tmp_path),
            memory_manager=memory,  # type: ignore[arg-type]
        ),
        conversation,
    )

    assert memory.turns == []


@pytest.mark.asyncio
async def test_agent_extracts_only_user_and_final_assistant_text(
    tmp_path: Path,
) -> None:
    tool_call = call("read-1", "read")
    provider = FakeProvider(
        [
            [complete(tool_call), end()],
            [TextDelta("最终答案"), end()],
        ]
    )
    memory = MemorySpy()
    conversation = Conversation.from_messages(
        [Message(role="user", content="请记住最终答案")]
    )

    await collect(
        Agent(
            provider,
            registry_with(InstrumentedTool("read", True)),
            runtime=runtime(tmp_path),
            memory_manager=memory,  # type: ignore[arg-type]
        ),
        conversation,
    )

    assert len(memory.turns) == 1
    assert memory.turns[0].user_text == "请记住最终答案"
    assert memory.turns[0].assistant_text == "最终答案"


def runtime(tmp_path: Path, context_window: int = 200000) -> SessionRuntime:
    return SessionRuntime(
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(tmp_path)),
        context_window=context_window,
    )


@pytest.mark.asyncio
async def test_agent_replaces_usage_anchor_with_latest_main_stream_usage(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([[TextDelta("done"), end(100, 20)]])
    session_runtime = runtime(tmp_path)
    conversation = Conversation()
    conversation.add_user("hello")

    await collect(
        Agent(provider, Registry(), runtime=session_runtime),
        conversation,
    )

    assert session_runtime.usage_anchor == 120
    assert session_runtime.anchor_msg_len == 1


@pytest.mark.asyncio
async def test_agent_emits_auto_compact_events(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            [TextDelta("<summary>compressed</summary>"), end()],
            [TextDelta("done"), end(100, 20)],
        ]
    )
    conversation = Conversation()
    conversation.replace_history(
        [Message(role="user", content="old" * 30000)]
        + [Message(role="assistant", content="x" * 7000) for _ in range(5)]
    )

    events = await collect(
        Agent(provider, Registry(), runtime=runtime(tmp_path, 60000)),
        conversation,
    )
    compact_events = [event.compact for event in events if event.compact]

    assert [event.phase for event in compact_events] == [
        CompactPhase.BEFORE_AUTO,
        CompactPhase.AFTER_AUTO,
    ]
    assert compact_events[1].before > compact_events[1].after
    assert compact_events[1].err is None


@pytest.mark.asyncio
async def test_agent_appends_exactly_one_boundary_on_compaction(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        [
            [TextDelta("<summary>compressed</summary>"), end()],
            [TextDelta("done"), end(100, 20)],
        ]
    )
    sink = RecordingSink()
    conversation = Conversation(sink=sink)
    conversation.replace_history(
        [Message(role="user", content="old" * 30000)]
        + [Message(role="assistant", content="x" * 7000) for _ in range(5)]
    )

    await collect(
        Agent(provider, Registry(), runtime=runtime(tmp_path, 60000)),
        conversation,
    )

    assert len(sink.boundaries) == 1
    assert sink.messages == [Message(role="assistant", content="done")]
    assert all("old" not in message.content for message in sink.messages)
    assert conversation.messages()[0].content.startswith("## 历史会话摘要")


@pytest.mark.asyncio
async def test_agent_emergency_compacts_and_retries_main_request_once(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        [
            [StreamError(PromptTooLongError("too long"))],
            [TextDelta("<summary>recovered</summary>"), end()],
            [TextDelta("done"), end()],
        ]
    )
    conversation = Conversation()
    conversation.add_user("hello")

    events = await collect(
        Agent(provider, Registry(), runtime=runtime(tmp_path)),
        conversation,
    )
    compact_events = [event.compact for event in events if event.compact]

    assert [event.phase for event in compact_events] == [
        CompactPhase.BEFORE_EMERGENCY,
        CompactPhase.AFTER_EMERGENCY,
    ]
    assert events[-1].done is True
    assert provider.call_count == 3


@pytest.mark.asyncio
async def test_agent_does_not_emergency_compact_twice_after_retry_ptl(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        [
            [StreamError(PromptTooLongError("first"))],
            [TextDelta("<summary>recovered</summary>"), end()],
            [StreamError(PromptTooLongError("second"))],
        ]
    )
    conversation = Conversation()
    conversation.add_user("hello")

    events = await collect(
        Agent(provider, Registry(), runtime=runtime(tmp_path)),
        conversation,
    )

    assert provider.call_count == 3
    assert sum(event.compact is not None for event in events) == 2
    assert isinstance(
        [event.err for event in events if event.err][-1], PromptTooLongError
    )


@pytest.mark.asyncio
async def test_agent_records_clean_read_file_content_before_next_iteration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("line one\nline two", encoding="utf-8")
    tool_call = ToolCall(
        id="read-1",
        name="read_file",
        input=json.dumps({"path": str(path)}),
    )
    provider = FakeProvider(
        [
            [complete(tool_call), end()],
            [TextDelta("done"), end()],
        ]
    )
    session_runtime = runtime(tmp_path)
    registry = Registry()
    from Arkcode.tools.builtins.read_file import ReadFileTool

    registry.register(ReadFileTool())
    conversation = Conversation()
    conversation.add_user("read")

    await collect(
        Agent(provider, registry, runtime=session_runtime),
        conversation,
    )

    record = session_runtime.recovery.snapshot()[0]
    assert record.path == str(path)
    assert record.content == "line one\nline two"


@pytest.mark.asyncio
async def test_long_agent_session_auto_compacts_and_reaches_final_response(
    tmp_path: Path,
) -> None:
    provider = LongSessionProvider()
    registry = registry_with(LargeResultTool("large_read", True))
    conversation = Conversation()
    conversation.add_user("work for many iterations")

    events = await collect(
        Agent(provider, registry, runtime=runtime(tmp_path, 50000)),
        conversation,
    )

    assert provider.main_calls == MAX_ITERATIONS
    assert provider.summary_calls >= 1
    assert events[-1].done is True
    assert conversation.messages()[-1].content == "long session complete"
    assert conversation.length() < 50


@pytest.mark.asyncio
async def test_agent_runs_multiple_iterations_until_plain_text_completion() -> None:
    tool_call = call("call-1", "read_file")
    provider = FakeProvider(
        [
            [
                TextDelta("先读取"),
                complete(tool_call),
                end(10, 2),
            ],
            [
                TextDelta("任务完成"),
                end(20, 4),
            ],
        ]
    )
    conversation = Conversation()
    conversation.add_user("读取并回答")

    events = await collect(
        Agent(
            provider,
            registry_with(InstrumentedTool("read_file", True)),
        ),
        conversation,
    )

    assert [event.iter for event in events if event.iter] == [1, 2]
    assert [event.text for event in events if event.text] == [
        "先读取",
        "任务完成",
    ]
    assert [
        (event.usage.input, event.usage.output) for event in events if event.usage
    ] == [
        (10, 2),
        (20, 4),
    ]
    assert [event.tool.phase for event in events if event.tool] == [
        Phase.START,
        Phase.END,
    ]
    assert events[-1].done is True
    assert provider.call_count == 2
    assert [message.role for message in conversation.messages()] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert conversation.messages()[-1].content == "任务完成"


@pytest.mark.asyncio
async def test_agent_stops_at_iteration_limit_with_legal_history() -> None:
    provider = RepeatingToolProvider()
    conversation = Conversation()
    conversation.add_user("一直调用")

    events = await collect(
        Agent(
            provider,
            registry_with(InstrumentedTool("read_file", True)),
        ),
        conversation,
    )

    assert provider.call_count == MAX_ITERATIONS
    assert [event.notice for event in events if event.notice] == [NOTICE_MAX_ITER]
    assert events[-1].done is True
    assert conversation.last_role() == "assistant"
    assert conversation.messages()[-1].content == NOTICE_MAX_ITER


@pytest.mark.asyncio
async def test_agent_stops_after_consecutive_unknown_tool_only_iterations() -> None:
    provider = RepeatingToolProvider("hallucinated")
    conversation = Conversation()
    conversation.add_user("调用未知工具")

    events = await collect(Agent(provider, Registry()), conversation)

    assert provider.call_count == MAX_UNKNOWN_RUN
    assert [event.notice for event in events if event.notice] == [NOTICE_UNKNOWN_TOOLS]
    assert conversation.last_role() == "assistant"


@pytest.mark.asyncio
async def test_known_tool_resets_unknown_iteration_counter() -> None:
    scripts = [
        [complete(call("u1", "missing")), end()],
        [complete(call("u2", "missing")), end()],
        [
            complete(call("known", "read_file")),
            end(),
        ],
        [complete(call("u3", "missing")), end()],
        [complete(call("u4", "missing")), end()],
        [TextDelta("已纠正"), end()],
    ]
    provider = FakeProvider(scripts)
    conversation = Conversation()
    conversation.add_user("纠正未知工具")

    events = await collect(
        Agent(
            provider,
            registry_with(InstrumentedTool("read_file", True)),
        ),
        conversation,
    )

    assert provider.call_count == 6
    assert not [event for event in events if event.notice]
    assert conversation.messages()[-1].content == "已纠正"


@pytest.mark.asyncio
async def test_read_only_batch_runs_concurrently_before_side_effect() -> None:
    tracker = Tracker()
    provider = FakeProvider(
        [
            [
                complete(call("r1", "read_file", "read-1")),
                complete(call("r2", "read_file", "read-2")),
                complete(call("w1", "write_file", "write")),
                end(),
            ],
            [TextDelta("完成"), end()],
        ]
    )
    registry = registry_with(
        InstrumentedTool("read_file", True, 0.03, tracker),
        InstrumentedTool("write_file", False, 0, tracker),
    )
    conversation = Conversation()
    conversation.add_user("并发读取后写入")

    events = await collect(Agent(provider, registry), conversation)

    assert tracker.peak >= 2
    assert tracker.starts[:2] == ["read-1", "read-2"]
    assert tracker.ends.index("read-1") < tracker.starts.index("write")
    assert tracker.ends.index("read-2") < tracker.starts.index("write")
    tool_events = [event.tool for event in events if event.tool]
    assert [event.phase for event in tool_events] == [
        Phase.START,
        Phase.START,
        Phase.END,
        Phase.END,
        Phase.START,
        Phase.END,
    ]
    tool_results = conversation.messages()[2].tool_results
    assert [result.tool_call_id for result in tool_results] == ["r1", "r2", "w1"]
    assert [result.content for result in tool_results] == [
        "read-1",
        "read-2",
        "write",
    ]


@pytest.mark.asyncio
async def test_cancellation_fills_results_and_allows_next_turn() -> None:
    provider = FakeProvider(
        [
            [
                complete(call("r1", "read_file", "slow-1")),
                complete(call("r2", "read_file", "slow-2")),
                end(),
            ],
            [TextDelta("取消后继续成功"), end()],
        ]
    )
    conversation = Conversation()
    conversation.add_user("开始慢任务")
    cancel = asyncio.Event()
    agent = Agent(
        provider,
        registry_with(InstrumentedTool("read_file", True, 1)),
    )
    events = []

    async for event in agent.run(conversation, Mode.NORMAL, cancel):
        events.append(event)
        if event.tool and event.tool.phase is Phase.START:
            cancel.set()

    assert conversation.last_role() == "assistant"
    assert conversation.messages()[-1].content == NOTICE_CANCELLED
    results = conversation.messages()[-2].tool_results
    assert [result.tool_call_id for result in results] == ["r1", "r2"]
    assert all(result.is_error for result in results)
    assert all(result.content == NOTICE_CANCELLED for result in results)

    conversation.add_user("继续")
    next_events = await collect(agent, conversation)

    assert next_events[-1].done is True
    assert conversation.messages()[-1].content == "取消后继续成功"


@pytest.mark.asyncio
async def test_stream_error_stops_with_assistant_tail() -> None:
    provider = FakeProvider([[StreamError(RuntimeError("network failed"))]])
    conversation = Conversation()
    conversation.add_user("会失败")

    events = await collect(Agent(provider, Registry()), conversation)

    assert isinstance([event.err for event in events if event.err][0], RuntimeError)
    assert conversation.last_role() == "assistant"
    assert conversation.messages()[-1].content == NOTICE_STREAM_ERR


@pytest.mark.asyncio
async def test_plan_mode_exposes_only_read_only_tools_and_suffix() -> None:
    provider = FakeProvider([[TextDelta("计划完成"), end()]])
    registry = registry_with(
        InstrumentedTool("read_file", True),
        InstrumentedTool("write_file", False),
    )
    conversation = Conversation()
    conversation.add_user("先计划")

    await collect(
        Agent(provider, registry),
        conversation,
        mode=Mode.PLAN,
    )

    _, tools, suffix = provider.received[0]
    assert [tool.name for tool in tools] == ["read_file"]
    assert suffix == plan_reminder(full=True)
    assert provider.requests[0].system.stable
    assert provider.requests[0].system.environment


@pytest.mark.asyncio
async def test_plan_reminder_frequency_and_history_isolation() -> None:
    scripts = [
        [complete(call(f"read-{index}", "read_file")), end()] for index in range(1, 5)
    ]
    scripts.append([TextDelta("计划完成"), end()])
    provider = FakeProvider(scripts)
    conversation = Conversation()
    conversation.add_user("多轮调研后给计划")

    await collect(
        Agent(provider, registry_with(InstrumentedTool("read_file", True))),
        conversation,
        mode=Mode.PLAN,
    )

    assert [request.reminder for request in provider.requests] == [
        plan_reminder(full=True),
        plan_reminder(full=False),
        plan_reminder(full=False),
        plan_reminder(full=False),
        plan_reminder(full=True),
    ]
    assert all(
        "<system-reminder>" not in message.content
        for message in conversation.messages()
    )


@pytest.mark.asyncio
async def test_deferred_tool_reminder_refreshes_without_entering_history(
    tmp_path: Path,
) -> None:
    deferred = InstrumentedTool("mcp__demo__search", True)
    deferred.should_defer = True
    registry = Registry()
    registry.register(ToolSearchTool(registry))
    registry.register(deferred)
    provider = FakeProvider(
        [
            [
                ToolCallComplete(
                    "discover-1",
                    "ToolSearch",
                    {"query": "select:mcp__demo__search"},
                ),
                end(),
            ],
            [TextDelta("完成"), end()],
        ]
    )
    session_dir = tmp_path / "session"
    journal = SessionJournal(session_dir)
    conversation = Conversation(sink=journal)
    with journal:
        conversation.add_user("搜索远程数据")
        await collect(Agent(provider, registry), conversation)

    first, second = provider.requests
    assert "mcp__demo__search" in first.reminder
    assert "mcp__demo__search" not in second.reminder
    assert [tool.name for tool in first.tools] == ["ToolSearch"]
    assert [tool.name for tool in second.tools] == [
        "ToolSearch",
        "mcp__demo__search",
    ]
    assert all(
        "The following deferred tools" not in message.content
        for message in conversation.messages()
    )
    transcript = (session_dir / "conversation.jsonl").read_text()
    assert "The following deferred tools" not in transcript


@pytest.mark.asyncio
async def test_plan_and_deferred_reminders_coexist() -> None:
    provider = FakeProvider([[TextDelta("计划完成"), end()]])
    deferred = InstrumentedTool("mcp__demo__read", True)
    deferred.should_defer = True
    registry = Registry()
    registry.register(ToolSearchTool(registry))
    registry.register(deferred)
    conversation = Conversation()
    conversation.add_user("先查远程资料再计划")

    await collect(Agent(provider, registry), conversation, mode=Mode.PLAN)

    _, tools, suffix = provider.received[0]
    expected_deferred = deferred_tools_reminder(["mcp__demo__read"])
    assert [tool.name for tool in tools] == ["ToolSearch"]
    assert suffix == combine_reminders(plan_reminder(full=True), expected_deferred)
    assert suffix.count("<system-reminder>") == 2
    assert provider.requests[0].system.stable
    assert all(
        "The following deferred tools" not in message.content
        for message in conversation.messages()
    )


@pytest.mark.asyncio
async def test_deferred_reminder_is_reused_for_emergency_retry(
    tmp_path: Path,
) -> None:
    deferred = InstrumentedTool("mcp__demo__search", True)
    deferred.should_defer = True
    registry = registry_with(deferred)
    provider = FakeProvider(
        [
            [StreamError(PromptTooLongError("too long"))],
            [TextDelta("<summary>recovered</summary>"), end()],
            [TextDelta("done"), end()],
        ]
    )
    conversation = Conversation()
    conversation.add_user("hello")

    await collect(Agent(provider, registry, runtime=runtime(tmp_path)), conversation)

    main_requests = [
        request for request in provider.requests if request.tools is not None
    ]
    assert len(main_requests) == 2
    assert main_requests[0].reminder == main_requests[1].reminder
    assert "mcp__demo__search" in main_requests[0].reminder


@pytest.mark.asyncio
async def test_large_tool_result_is_final_before_sink_and_memory(
    tmp_path: Path,
) -> None:
    class OversizedResultTool(InstrumentedTool):
        async def execute(self, params: InstrumentedParams) -> Result:
            return Result("x" * 60000)

    tool_call = call("large-1", "large_read")
    provider = FakeProvider(
        [
            [complete(tool_call), end()],
            [TextDelta("完成"), end()],
        ]
    )
    sink = RecordingSink()
    conversation = Conversation(sink=sink)
    conversation.add_user("读取大结果")
    session_runtime = runtime(tmp_path)
    registry = registry_with(OversizedResultTool("large_read", True))

    await collect(
        Agent(provider, registry, runtime=session_runtime),
        conversation,
    )

    memory_result = conversation.messages()[2].tool_results[0]
    sink_result = sink.messages[2].tool_results[0]
    assert memory_result.content == sink_result.content
    assert memory_result.content.startswith("[content offloaded]")
    spill_files = list(Path(session_runtime.session.spill_dir).iterdir())
    assert len(spill_files) == 1
    assert spill_files[0].read_text(encoding="utf-8") == "x" * 60000


@pytest.mark.asyncio
async def test_stable_system_is_identical_across_default_and_plan_modes() -> None:
    registry = registry_with(
        InstrumentedTool("read_file", True),
        InstrumentedTool("write_file", False),
    )
    default_provider = FakeProvider([[TextDelta("普通完成"), end()]])
    plan_provider = FakeProvider([[TextDelta("计划完成"), end()]])
    default_conversation = Conversation()
    plan_conversation = Conversation()
    default_conversation.add_user("执行")
    plan_conversation.add_user("计划")

    await collect(Agent(default_provider, registry), default_conversation)
    await collect(
        Agent(plan_provider, registry),
        plan_conversation,
        mode=Mode.PLAN,
    )

    default_request = default_provider.requests[0]
    plan_request = plan_provider.requests[0]
    assert default_request.system.stable == plan_request.system.stable
    assert default_request.system.stable
    assert default_request.system.environment
    assert plan_request.system.environment
    assert [tool.name for tool in default_request.tools] == [
        "read_file",
        "write_file",
    ]
    assert [tool.name for tool in plan_request.tools] == ["read_file"]


@pytest.mark.asyncio
async def test_plan_mode_refuses_side_effect_call_returned_by_provider() -> None:
    tracker = Tracker()
    provider = FakeProvider(
        [
            [
                complete(call("write-1", "write_file")),
                end(),
            ],
            [TextDelta("未执行写入"), end()],
        ]
    )
    conversation = Conversation()
    conversation.add_user("只制定计划")

    await collect(
        Agent(
            provider,
            registry_with(
                InstrumentedTool("read_file", True),
                InstrumentedTool("write_file", False, tracker=tracker),
            ),
        ),
        conversation,
        mode=Mode.PLAN,
    )

    assert tracker.starts == []
    result = conversation.messages()[2].tool_results[0]
    assert result.tool_call_id == "write-1"
    assert result.is_error is True
    assert "Plan Mode" in result.content


@pytest.mark.asyncio
async def test_plan_mode_refuses_install_skill_with_permission_engine(
    tmp_path: Path,
) -> None:
    tracker = Tracker()
    provider = FakeProvider(
        [
            [complete(call("install-1", "InstallSkill")), end()],
            [TextDelta("未安装"), end()],
        ]
    )
    conversation = Conversation()
    conversation.add_user("只做计划")
    engine, error = new_engine(str(tmp_path))
    assert error is None

    events = await collect(
        Agent(
            provider,
            registry_with(
                InstrumentedTool("InstallSkill", False, tracker=tracker),
            ),
            engine=engine,
        ),
        conversation,
        mode=Mode.PLAN,
    )

    assert tracker.starts == []
    assert not [event for event in events if event.approval is not None]
    result = conversation.messages()[2].tool_results[0]
    assert result.is_error is True
    assert "Plan Mode" in result.content


@pytest.mark.asyncio
async def test_direct_task_cancel_closes_pending_provider_stream() -> None:
    provider = BlockingProvider()
    conversation = Conversation()
    conversation.add_user("等待网络流")

    async def consume() -> None:
        async for _ in Agent(provider, Registry()).run(
            conversation,
            Mode.NORMAL,
            asyncio.Event(),
        ):
            pass

    task = asyncio.create_task(consume())
    await provider.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.closed.is_set()


@pytest.mark.asyncio
async def test_direct_task_cancel_stops_pending_tool_task() -> None:
    tracker = Tracker()
    provider = FakeProvider(
        [
            [
                complete(call("slow", "read_file")),
                end(),
            ]
        ]
    )
    conversation = Conversation()
    conversation.add_user("执行慢工具")
    agent = Agent(
        provider,
        registry_with(InstrumentedTool("read_file", True, 10, tracker)),
    )

    async def consume() -> None:
        async for _ in agent.run(
            conversation,
            Mode.NORMAL,
            asyncio.Event(),
        ):
            pass

    task = asyncio.create_task(consume())
    while tracker.active == 0:
        await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert tracker.active == 0


@pytest.mark.asyncio
async def test_agent_preserves_thinking_and_forwards_cache_usage_once() -> None:
    tool = call("read-1", "read_file")
    provider = FakeProvider(
        [
            [
                ThinkingDelta("先分析"),
                ThinkingComplete("先分析", "signed-thought"),
                complete(tool),
                StreamEnd(
                    "tool_use",
                    20,
                    3,
                    cache_read=11,
                    cache_creation=5,
                    cache_write=5,
                ),
            ],
            [TextDelta("完成"), StreamEnd("end_turn", 30, 4, 12, 0)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("分析后读取")

    events = await collect(
        Agent(provider, registry_with(InstrumentedTool("read_file", True))),
        conversation,
    )

    assert [event.thinking for event in events if event.thinking] == ["先分析"]
    assert [
        (
            event.usage.input,
            event.usage.output,
            event.usage.cache_read,
            event.usage.cache_creation,
            event.usage.cache_write,
        )
        for event in events
        if event.usage
    ] == [(20, 3, 11, 5, 5), (30, 4, 12, 0, 0)]
    first_assistant = conversation.messages()[1]
    assert first_assistant.thinking == "先分析"
    assert first_assistant.thinking_signature == "signed-thought"
    assert first_assistant.content == ""


@pytest.mark.asyncio
async def test_agent_preserves_signed_thinking_on_a_final_text_reply() -> None:
    provider = FakeProvider(
        [
            [
                ThinkingDelta("先推理"),
                ThinkingComplete("先推理", "final-signature"),
                TextDelta("最终答复"),
                StreamEnd("end_turn"),
            ]
        ]
    )
    conversation = Conversation()
    conversation.add_user("直接回答")

    await collect(Agent(provider, Registry()), conversation)

    message = conversation.messages()[-1]
    assert message.content == "最终答复"
    assert message.thinking == "先推理"
    assert message.thinking_signature == "final-signature"


def permission_call(call_id: str, name: str, path: str, label: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        name=name,
        input=json.dumps({"path": path, "label": label}),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "executed", "is_error"),
    [
        (Outcome.ALLOW_ONCE, True, False),
        (Outcome.DENY_ONCE, False, True),
    ],
)
async def test_permission_approval_controls_side_effect_execution(
    tmp_path: Path,
    outcome: Outcome,
    executed: bool,
    is_error: bool,
) -> None:
    tracker = Tracker()
    requested = permission_call("write-1", "write_file", "result.txt", "write")
    provider = FakeProvider(
        [[complete(requested), end()], [TextDelta("继续完成"), end()]]
    )
    conversation = Conversation()
    conversation.add_user("写文件")
    engine, _ = new_engine(str(tmp_path))
    agent = Agent(
        provider,
        registry_with(InstrumentedTool("write_file", False, tracker=tracker)),
        engine=engine,
    )
    approvals = []

    async for event in agent.run(conversation, Mode.DEFAULT, asyncio.Event()):
        if event.approval is not None:
            approvals.append(event.approval)
            event.approval.respond.set_result(outcome)

    assert len(approvals) == 1
    assert bool(tracker.starts) is executed
    result = conversation.messages()[2].tool_results[0]
    assert result.tool_call_id == "write-1"
    assert result.is_error is is_error
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_install_skill_requires_default_mode_approval(tmp_path: Path) -> None:
    tracker = Tracker()
    requested = call("install-1", "InstallSkill")
    provider = FakeProvider(
        [[complete(requested), end()], [TextDelta("未安装"), end()]]
    )
    conversation = Conversation()
    conversation.add_user("安装 Skill")
    engine, error = new_engine(str(tmp_path))
    assert error is None
    agent = Agent(
        provider,
        registry_with(
            InstrumentedTool("InstallSkill", False, tracker=tracker),
        ),
        engine=engine,
    )
    approvals = []

    async for event in agent.run(conversation, Mode.DEFAULT, asyncio.Event()):
        if event.approval is not None:
            approvals.append(event.approval)
            event.approval.respond.set_result(Outcome.DENY_ONCE)

    assert [approval.name for approval in approvals] == ["InstallSkill"]
    assert tracker.starts == []


@pytest.mark.asyncio
async def test_permission_allow_forever_persists_and_reloads(tmp_path: Path) -> None:
    tracker = Tracker()
    requested = permission_call("write-1", "write_file", "saved.txt", "write")
    provider = FakeProvider(
        [[complete(requested), end()], [TextDelta("已保存"), end()]]
    )
    conversation = Conversation()
    conversation.add_user("永久放行")
    engine, _ = new_engine(str(tmp_path))
    agent = Agent(
        provider,
        registry_with(InstrumentedTool("write_file", False, tracker=tracker)),
        engine=engine,
    )

    async for event in agent.run(conversation, Mode.DEFAULT, asyncio.Event()):
        if event.approval is not None:
            event.approval.respond.set_result(Outcome.ALLOW_FOREVER)

    assert tracker.starts == ["write"]
    assert Path(engine.local_path).is_file()
    reloaded, _ = new_engine(str(tmp_path))
    decision, _ = reloaded.check(Mode.DEFAULT, requested, False)
    assert decision is Decision.ALLOW


@pytest.mark.asyncio
async def test_permission_read_batch_denies_outside_and_preserves_order(
    tmp_path: Path,
) -> None:
    tracker = Tracker()
    outside = permission_call("outside", "read_file", "/etc/passwd", "outside")
    inside = permission_call("inside", "read_file", "inside.txt", "inside")
    provider = FakeProvider(
        [
            [complete(outside), complete(inside), end()],
            [TextDelta("已调整"), end()],
        ]
    )
    conversation = Conversation()
    conversation.add_user("读取两个路径")
    engine, _ = new_engine(str(tmp_path))

    events = await collect(
        Agent(
            provider,
            registry_with(InstrumentedTool("read_file", True, tracker=tracker)),
            engine=engine,
        ),
        conversation,
    )

    assert not [event for event in events if event.approval is not None]
    results = conversation.messages()[2].tool_results
    assert [result.tool_call_id for result in results] == ["outside", "inside"]
    assert [result.is_error for result in results] == [True, False]
    assert tracker.starts == ["inside"]


@pytest.mark.asyncio
async def test_permission_cancel_while_waiting_for_approval_is_clean(
    tmp_path: Path,
) -> None:
    requested = permission_call("write-1", "write_file", "x.txt", "write")
    provider = FakeProvider([[complete(requested), end()]])
    conversation = Conversation()
    conversation.add_user("取消批准")
    engine, _ = new_engine(str(tmp_path))
    cancel = asyncio.Event()

    async for event in Agent(
        provider,
        registry_with(InstrumentedTool("write_file", False)),
        engine=engine,
    ).run(conversation, Mode.DEFAULT, cancel):
        if event.approval is not None:
            cancel.set()

    assert conversation.last_role() == "assistant"
    assert conversation.messages()[-1].content == NOTICE_CANCELLED
    assert conversation.messages()[-2].tool_results[0].is_error is True


@pytest.mark.asyncio
async def test_accept_edits_allows_write_but_still_asks_for_exec(
    tmp_path: Path,
) -> None:
    tracker = Tracker()
    write = permission_call("write", "write_file", "ok.txt", "write")
    bash = ToolCall(
        id="bash",
        name="bash",
        input=json.dumps({"command": "git status", "label": "bash"}),
    )
    provider = FakeProvider(
        [[complete(write), complete(bash), end()], [TextDelta("完成"), end()]]
    )
    conversation = Conversation()
    conversation.add_user("写入并检查")
    engine, _ = new_engine(str(tmp_path))
    agent = Agent(
        provider,
        registry_with(
            InstrumentedTool("write_file", False, tracker=tracker),
            InstrumentedTool("bash", False, tracker=tracker),
        ),
        engine=engine,
    )
    approvals = []

    async for event in agent.run(
        conversation,
        Mode.ACCEPT_EDITS,
        asyncio.Event(),
    ):
        if event.approval is not None:
            approvals.append(event.approval.name)
            event.approval.respond.set_result(Outcome.DENY_ONCE)

    assert tracker.starts == ["write"]
    assert approvals == ["bash"]
    assert [r.is_error for r in conversation.messages()[2].tool_results] == [
        False,
        True,
    ]


@pytest.mark.asyncio
async def test_denied_outside_write_is_recovered_with_inside_path(
    tmp_path: Path,
) -> None:
    tracker = Tracker()
    outside = permission_call("outside", "write_file", "../escape.txt", "outside")
    inside = permission_call("inside", "write_file", "inside.txt", "inside")
    provider = FakeProvider(
        [
            [complete(outside), end()],
            [complete(inside), end()],
            [TextDelta("已改用项目内路径"), end()],
        ]
    )
    conversation = Conversation()
    conversation.add_user("写入文件")
    engine, _ = new_engine(str(tmp_path))
    agent = Agent(
        provider,
        registry_with(InstrumentedTool("write_file", False, tracker=tracker)),
        engine=engine,
    )

    async for event in agent.run(conversation, Mode.DEFAULT, asyncio.Event()):
        if event.approval is not None:
            event.approval.respond.set_result(Outcome.ALLOW_ONCE)

    first = conversation.messages()[2].tool_results[0]
    second = conversation.messages()[4].tool_results[0]
    assert first.is_error is True
    assert "项目目录之外" in first.content
    assert second.is_error is False
    assert tracker.starts == ["inside"]
    assert conversation.messages()[-1].content == "已改用项目内路径"


@pytest.mark.asyncio
async def test_direct_cancel_during_approval_closes_future_and_history(
    tmp_path: Path,
) -> None:
    requested = permission_call("write", "write_file", "x.txt", "write")
    provider = FakeProvider([[complete(requested), end()]])
    conversation = Conversation()
    conversation.add_user("等待审批")
    engine, _ = new_engine(str(tmp_path))
    approval_ready: asyncio.Future[Any] = asyncio.get_running_loop().create_future()

    async def consume() -> None:
        async for event in Agent(
            provider,
            registry_with(InstrumentedTool("write_file", False)),
            engine=engine,
        ).run(conversation, Mode.DEFAULT, asyncio.Event()):
            if event.approval is not None and not approval_ready.done():
                approval_ready.set_result(event.approval)

    task = asyncio.create_task(consume())
    approval = await asyncio.wait_for(approval_ready, timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert approval.respond.cancelled()
    assert conversation.last_role() == "assistant"
    assert conversation.messages()[-1].content == NOTICE_CANCELLED
    assert conversation.messages()[-2].tool_results[0].tool_call_id == "write"
