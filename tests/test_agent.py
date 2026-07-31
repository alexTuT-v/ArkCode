"""Agent ReAct 循环、停止条件与并发策略测试。"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from Arkcode.agent import (
    MAX_ITERATIONS,
    MAX_UNKNOWN_RUN,
    NOTICE_CANCELLED,
    NOTICE_MAX_ITER,
    NOTICE_STREAM_ERR,
    NOTICE_UNKNOWN_TOOLS,
    Agent,
    Mode,
    Phase,
)
from Arkcode.conversation import Conversation
from Arkcode.llm import (
    Message,
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
from Arkcode.prompt import PLAN_MODE_REMINDER
from Arkcode.tool import Registry, Result


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.call_count = 0
        self.received: list[tuple[list[Message], list[ToolDefinition], str]] = []

    async def stream(
        self,
        msgs: list[Message],
        tools: list[ToolDefinition],
        system_suffix: str = "",
    ) -> AsyncIterator[StreamEvent]:
        self.received.append((msgs, tools, system_suffix))
        script = self.scripts[self.call_count]
        self.call_count += 1
        for event in script:
            yield event


class RepeatingToolProvider(FakeProvider):
    def __init__(self, tool_name: str = "read_file") -> None:
        super().__init__([])
        self.tool_name = tool_name

    async def stream(
        self,
        msgs: list[Message],
        tools: list[ToolDefinition],
        system_suffix: str = "",
    ) -> AsyncIterator[StreamEvent]:
        self.received.append((msgs, tools, system_suffix))
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

    async def stream(
        self,
        msgs: list[Message],
        tools: list[ToolDefinition],
        system_suffix: str = "",
    ) -> AsyncIterator[StreamEvent]:
        self.received.append((msgs, tools, system_suffix))
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.closed.set()
        yield end()


@dataclass
class Tracker:
    active: int = 0
    peak: int = 0
    starts: list[str] = field(default_factory=list)
    ends: list[str] = field(default_factory=list)


@dataclass
class InstrumentedTool:
    tool_name: str
    read_only: bool
    delay: float = 0
    tracker: Tracker | None = None

    def name(self) -> str:
        return self.tool_name

    def description(self) -> str:
        return self.tool_name

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: str) -> Result:
        label = json.loads(args or "{}").get("label", self.tool_name)
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
    assert suffix == PLAN_MODE_REMINDER


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
                StreamEnd("tool_use", 20, 3, 11, 5),
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
        )
        for event in events
        if event.usage
    ] == [(20, 3, 11, 5), (30, 4, 12, 0)]
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
