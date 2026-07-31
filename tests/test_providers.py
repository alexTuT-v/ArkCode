import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from Arkcode.config import ProviderConfig
from Arkcode.llm import (
    ROLE_TOOL,
    Message,
    StreamEnd,
    StreamError,
    StreamEvent,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCall,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
    ToolDefinition,
    ToolResult,
    new_provider,
)
from Arkcode.llm.anthropic_provider import AnthropicProvider
from Arkcode.llm.openai_provider import OpenAIProvider
from Arkcode.prompt import SYSTEM_PROMPT


async def collect(events: AsyncIterator[StreamEvent]) -> list[StreamEvent]:
    return [event async for event in events]


class FakeAnthropicStream:
    def __init__(self, events: list[Any], final_message: Any | None = None) -> None:
        self.events = events
        self.final_message = final_message or SimpleNamespace(
            stop_reason="end_turn",
            content=[],
            usage=SimpleNamespace(input_tokens=0, output_tokens=0),
        )

    async def __aenter__(self) -> "FakeAnthropicStream":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[Any]:
        async def iterate() -> AsyncIterator[Any]:
            for event in self.events:
                yield event

        return iterate()

    async def get_final_message(self) -> Any:
        return self.final_message


class FakeAnthropicMessages:
    def __init__(self, events: list[Any], final_message: Any | None = None) -> None:
        self.events = events
        self.final_message = final_message
        self.params: dict[str, Any] = {}

    def stream(self, **params: Any) -> FakeAnthropicStream:
        self.params = params
        return FakeAnthropicStream(self.events, self.final_message)


class FailingAnthropicMessages:
    def stream(self, **params: Any) -> FakeAnthropicStream:
        raise RuntimeError("anthropic unavailable")


class FakeOpenAIStream:
    def __init__(self, chunks: list[Any]) -> None:
        self.chunks = chunks

    def __aiter__(self) -> AsyncIterator[Any]:
        async def iterate() -> AsyncIterator[Any]:
            for chunk in self.chunks:
                yield chunk

        return iterate()


class FakeOpenAICompletions:
    def __init__(self, chunks: list[Any]) -> None:
        self.chunks = chunks
        self.params: dict[str, Any] = {}

    async def create(self, **params: Any) -> FakeOpenAIStream:
        self.params = params
        return FakeOpenAIStream(self.chunks)


class FailingOpenAICompletions:
    async def create(self, **params: Any) -> FakeOpenAIStream:
        raise RuntimeError("openai unavailable")


def anthropic_config(*, thinking: bool = False) -> ProviderConfig:
    return ProviderConfig(
        name="Claude",
        protocol="anthropic",
        api_key="secret",
        model="claude-test",
        base_url="https://anthropic.example",
        thinking=thinking,
    )


def openai_config() -> ProviderConfig:
    return ProviderConfig(
        name="GPT",
        protocol="openai",
        api_key="secret",
        model="gpt-test",
        base_url="https://openai.example/v1",
    )


def test_factory_selects_protocol_adapter() -> None:
    assert isinstance(new_provider(anthropic_config()), AnthropicProvider)
    assert isinstance(new_provider(openai_config()), OpenAIProvider)


def test_stream_events_keep_tool_fragments_and_terminal_states_distinct() -> None:
    """避免交错工具分片归属错误或把错误当作正常结束。"""

    events: list[StreamEvent] = [
        TextDelta("准备读取"),
        ToolCallStart(tool_name="read_file", tool_id="call-a"),
        ToolCallStart(tool_name="read_file", tool_id="call-b"),
        ToolCallDelta(tool_id="call-a", text='{"path":"a'),
        ToolCallDelta(tool_id="call-b", text='{"path":"b'),
        ToolCallComplete(
            tool_id="call-a",
            tool_name="read_file",
            arguments={"path": "a.txt"},
        ),
        StreamEnd(
            stop_reason="tool_use",
            input_tokens=10,
            output_tokens=2,
            cache_read=7,
            cache_creation=3,
        ),
    ]

    assert events[3].tool_id == "call-a"
    assert events[4].tool_id == "call-b"
    assert events[-1] == StreamEnd("tool_use", 10, 2, 7, 3)
    assert not isinstance(StreamError(RuntimeError("network")), StreamEnd)


def test_anthropic_streams_text_and_thinking_with_history() -> None:
    provider = AnthropicProvider(anthropic_config(thinking=True))
    messages_api = FakeAnthropicMessages(
        [
            SimpleNamespace(
                type="content_block_start",
                index=0,
                content_block=SimpleNamespace(type="thinking"),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="thinking_delta", thinking="secret thought"),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="signature_delta", signature="sig-1"),
            ),
            SimpleNamespace(type="content_block_stop", index=0),
            SimpleNamespace(
                type="content_block_start",
                index=1,
                content_block=SimpleNamespace(type="text"),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text="你好"),
            ),
            SimpleNamespace(type="content_block_stop", index=1),
            SimpleNamespace(type="message_stop"),
        ]
    )
    provider._client = SimpleNamespace(messages=messages_api)
    history = [
        Message(role="user", content="第一轮"),
        Message(role="assistant", content="上一条回复"),
        Message(role="user", content="第二轮"),
    ]

    events = asyncio.run(collect(provider.stream(history, [])))

    assert events == [
        ThinkingDelta("secret thought"),
        ThinkingComplete("secret thought", "sig-1"),
        TextDelta("你好"),
        StreamEnd("end_turn"),
    ]
    assert messages_api.params == {
        "model": "claude-test",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": "第一轮"},
            {"role": "assistant", "content": "上一条回复"},
            {"role": "user", "content": "第二轮"},
        ],
        "thinking": {"type": "enabled", "budget_tokens": 2048},
    }


def test_anthropic_emits_error_event_instead_of_raising() -> None:
    provider = AnthropicProvider(anthropic_config())
    provider._client = SimpleNamespace(messages=FailingAnthropicMessages())

    events = asyncio.run(collect(provider.stream([], [])))

    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert isinstance(events[0].error, RuntimeError)
    assert str(events[0].error) == "anthropic unavailable"


def test_openai_streams_text_and_sends_system_with_history() -> None:
    provider = OpenAIProvider(openai_config())
    completions = FakeOpenAICompletions(
        [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello"))]
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="!"))]
            ),
        ]
    )
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    history = [
        Message(role="user", content="第一轮"),
        Message(role="assistant", content="上一条回复"),
    ]

    events = asyncio.run(collect(provider.stream(history, [])))

    assert events == [
        TextDelta("Hello"),
        TextDelta("!"),
        StreamEnd("unknown"),
    ]
    assert completions.params == {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "第一轮"},
            {"role": "assistant", "content": "上一条回复"},
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def test_openai_emits_error_event_instead_of_raising() -> None:
    provider = OpenAIProvider(openai_config())
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=FailingOpenAICompletions())
    )

    events = asyncio.run(collect(provider.stream([], [])))

    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert isinstance(events[0].error, RuntimeError)
    assert str(events[0].error) == "openai unavailable"


def test_anthropic_appends_system_suffix_and_emits_usage() -> None:
    provider = AnthropicProvider(anthropic_config())
    final_message = SimpleNamespace(
        stop_reason="end_turn",
        content=[],
        usage=SimpleNamespace(
            input_tokens=17,
            output_tokens=5,
            cache_read_input_tokens=9,
            cache_creation_input_tokens=4,
        ),
    )
    messages_api = FakeAnthropicMessages([], final_message)
    provider._client = SimpleNamespace(messages=messages_api)

    events = asyncio.run(collect(provider.stream([], [], "PLAN ONLY")))

    assert messages_api.params["system"] == SYSTEM_PROMPT + "\n\nPLAN ONLY"
    assert events == [
        StreamEnd(
            "end_turn",
            input_tokens=17,
            output_tokens=5,
            cache_read=9,
            cache_creation=4,
        ),
    ]


def test_anthropic_injects_tools_and_converts_tool_history() -> None:
    provider = AnthropicProvider(anthropic_config(thinking=True))
    final_message = SimpleNamespace(
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=3, output_tokens=4),
        content=[
            SimpleNamespace(
                type="tool_use",
                id="tool-1",
                name="read_file",
                input={"path": "a.txt"},
            )
        ],
    )
    messages_api = FakeAnthropicMessages(
        [
            SimpleNamespace(
                type="content_block_start",
                index=0,
                content_block=SimpleNamespace(
                    type="tool_use",
                    id="tool-1",
                    name="read_file",
                ),
            ),
            SimpleNamespace(
                type="content_block_delta",
                index=0,
                delta=SimpleNamespace(
                    type="input_json_delta", partial_json='{"path":"a.txt"}'
                ),
            ),
            SimpleNamespace(type="content_block_stop", index=0),
        ],
        final_message,
    )
    provider._client = SimpleNamespace(messages=messages_api)
    definition = ToolDefinition(
        name="read_file",
        description="读取文件",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    history = [
        Message(
            role="assistant",
            content="读取中",
            thinking="先判断文件路径",
            thinking_signature="signed-thinking",
            tool_calls=[
                ToolCall(id="old-1", name="read_file", input='{"path":"old.txt"}')
            ],
        ),
        Message(
            role=ROLE_TOOL,
            tool_results=[
                ToolResult(tool_call_id="old-1", content="not found", is_error=True)
            ],
        ),
    ]

    events = asyncio.run(collect(provider.stream(history, [definition])))

    assert events == [
        ToolCallStart("read_file", "tool-1"),
        ToolCallDelta("tool-1", '{"path":"a.txt"}'),
        ToolCallComplete("tool-1", "read_file", {"path": "a.txt"}),
        StreamEnd("tool_use", input_tokens=3, output_tokens=4),
    ]
    assert messages_api.params["tools"] == [
        {
            "name": "read_file",
            "description": "读取文件",
            "input_schema": definition.input_schema,
        }
    ]
    assert messages_api.params["messages"] == [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "thinking",
                    "thinking": "先判断文件路径",
                    "signature": "signed-thinking",
                },
                {"type": "text", "text": "读取中"},
                {
                    "type": "tool_use",
                    "id": "old-1",
                    "name": "read_file",
                    "input": {"path": "old.txt"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "old-1",
                    "content": "not found",
                    "is_error": True,
                }
            ],
        },
    ]
    assert messages_api.params["thinking"] == {
        "type": "enabled",
        "budget_tokens": 2048,
    }


def test_anthropic_keeps_thinking_enabled_when_replaying_tool_history() -> None:
    provider = AnthropicProvider(anthropic_config(thinking=True))
    messages_api = FakeAnthropicMessages([])
    provider._client = SimpleNamespace(messages=messages_api)
    definition = ToolDefinition(
        name="read_file",
        description="读取文件",
        input_schema={"type": "object", "properties": {}, "required": []},
    )

    history = [
        Message(
            role="assistant",
            thinking="已分析",
            thinking_signature="signature",
            tool_calls=[ToolCall("call-1", "read_file", "{}")],
        ),
        Message(role=ROLE_TOOL, tool_results=[ToolResult("call-1", "结果")]),
    ]

    asyncio.run(collect(provider.stream(history, [definition])))

    assert messages_api.params["thinking"] == {
        "type": "enabled",
        "budget_tokens": 2048,
    }


def test_openai_joins_tool_call_fragments_and_converts_tool_history() -> None:
    provider = OpenAIProvider(openai_config())
    chunks = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call-1",
                                function=SimpleNamespace(
                                    name="read_file", arguments='{"path":'
                                ),
                            )
                        ],
                    ),
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id=None,
                                function=SimpleNamespace(
                                    name=None, arguments='"a.txt"}'
                                ),
                            )
                        ],
                    ),
                )
            ]
        ),
    ]
    completions = FakeOpenAICompletions(chunks)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    definition = ToolDefinition(
        name="read_file",
        description="读取文件",
        input_schema={"type": "object", "properties": {}, "required": []},
    )
    history = [
        Message(
            role="assistant",
            tool_calls=[
                ToolCall(id="old-1", name="read_file", input='{"path":"old.txt"}')
            ],
        ),
        Message(
            role=ROLE_TOOL,
            tool_results=[ToolResult(tool_call_id="old-1", content="old content")],
        ),
    ]

    events = asyncio.run(collect(provider.stream(history, [definition])))

    assert events == [
        ToolCallStart("read_file", "call-1"),
        ToolCallDelta("call-1", '{"path":'),
        ToolCallDelta("call-1", '"a.txt"}'),
        ToolCallComplete("call-1", "read_file", {"path": "a.txt"}),
        StreamEnd("tool_calls"),
    ]
    assert completions.params["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "读取文件",
                "parameters": definition.input_schema,
            },
        }
    ]
    assert completions.params["messages"][-2:] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "old-1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"old.txt"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "old-1", "content": "old content"},
    ]


def test_openai_keeps_interleaved_tool_fragments_with_their_call_ids() -> None:
    provider = OpenAIProvider(openai_config())
    completions = FakeOpenAICompletions(
        [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason=None,
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="call-a",
                                    function=SimpleNamespace(
                                        name="read_file", arguments='{"path":"a'
                                    ),
                                ),
                                SimpleNamespace(
                                    index=1,
                                    id="call-b",
                                    function=SimpleNamespace(
                                        name="read_file", arguments='{"path":"b'
                                    ),
                                ),
                            ],
                        ),
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id=None,
                                    function=SimpleNamespace(
                                        name=None, arguments='.txt"}'
                                    ),
                                ),
                                SimpleNamespace(
                                    index=1,
                                    id=None,
                                    function=SimpleNamespace(
                                        name=None, arguments='.txt"}'
                                    ),
                                ),
                            ],
                        ),
                    )
                ]
            ),
        ]
    )
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    events = asyncio.run(collect(provider.stream([], [])))

    assert events == [
        ToolCallStart("read_file", "call-a"),
        ToolCallDelta("call-a", '{"path":"a'),
        ToolCallStart("read_file", "call-b"),
        ToolCallDelta("call-b", '{"path":"b'),
        ToolCallDelta("call-a", '.txt"}'),
        ToolCallDelta("call-b", '.txt"}'),
        ToolCallComplete("call-a", "read_file", {"path": "a.txt"}),
        ToolCallComplete("call-b", "read_file", {"path": "b.txt"}),
        StreamEnd("tool_calls"),
    ]


@pytest.mark.asyncio
async def test_openai_emits_tool_start_and_argument_delta_before_stream_ends() -> None:
    release = asyncio.Event()
    first = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=None,
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id="call-live",
                            function=SimpleNamespace(
                                name="read_file", arguments='{"path":"a'
                            ),
                        )
                    ],
                ),
            )
        ]
    )
    second = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id=None,
                            function=SimpleNamespace(name=None, arguments='.txt"}'),
                        )
                    ],
                ),
            )
        ]
    )

    class PausingStream:
        def __aiter__(self) -> AsyncIterator[Any]:
            async def iterate() -> AsyncIterator[Any]:
                yield first
                await release.wait()
                yield second

            return iterate()

    class PausingCompletions:
        async def create(self, **params: Any) -> PausingStream:
            return PausingStream()

    provider = OpenAIProvider(openai_config())
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=PausingCompletions())
    )
    events: list[StreamEvent] = []

    async def consume() -> None:
        async for event in provider.stream([], []):
            events.append(event)

    task = asyncio.create_task(consume())
    for _ in range(10):
        await asyncio.sleep(0)
        if events:
            break

    assert events == [
        ToolCallStart("read_file", "call-live"),
        ToolCallDelta("call-live", '{"path":"a'),
    ]
    release.set()
    await task


def test_openai_appends_system_suffix_and_emits_usage_chunk() -> None:
    provider = OpenAIProvider(openai_config())
    completions = FakeOpenAICompletions(
        [
            SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=23,
                    completion_tokens=8,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=13),
                ),
            )
        ]
    )
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    events = asyncio.run(collect(provider.stream([], [], "PLAN ONLY")))

    assert completions.params["messages"][0] == {
        "role": "system",
        "content": SYSTEM_PROMPT + "\n\nPLAN ONLY",
    }
    assert completions.params["stream_options"] == {"include_usage": True}
    assert events == [
        StreamEnd("unknown", input_tokens=23, output_tokens=8, cache_read=13),
    ]


def test_openai_emits_usage_when_compatible_endpoint_keeps_final_choice() -> None:
    provider = OpenAIProvider(openai_config())
    completions = FakeOpenAICompletions(
        [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        delta=SimpleNamespace(content=None, tool_calls=None),
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=31, completion_tokens=9),
            )
        ]
    )
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    events = asyncio.run(collect(provider.stream([], [])))

    assert events == [
        StreamEnd("stop", input_tokens=31, output_tokens=9),
    ]
