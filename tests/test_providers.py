import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from Arkcode.config import ProviderConfig
from Arkcode.llm import Message, StreamEvent, new_provider
from Arkcode.llm.anthropic_provider import AnthropicProvider
from Arkcode.llm.openai_provider import OpenAIProvider
from Arkcode.prompt import SYSTEM_PROMPT


async def collect(events: AsyncIterator[StreamEvent]) -> list[StreamEvent]:
    return [event async for event in events]


class FakeAnthropicStream:
    def __init__(self, events: list[Any]) -> None:
        self.events = events

    async def __aenter__(self) -> "FakeAnthropicStream":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[Any]:
        async def iterate() -> AsyncIterator[Any]:
            for event in self.events:
                yield event

        return iterate()


class FakeAnthropicMessages:
    def __init__(self, events: list[Any]) -> None:
        self.events = events
        self.params: dict[str, Any] = {}

    def stream(self, **params: Any) -> FakeAnthropicStream:
        self.params = params
        return FakeAnthropicStream(self.events)


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


def test_anthropic_streams_text_discards_thinking_and_sends_history() -> None:
    provider = AnthropicProvider(anthropic_config(thinking=True))
    messages_api = FakeAnthropicMessages(
        [
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="thinking_delta", thinking="secret thought"),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text="你好"),
            ),
            SimpleNamespace(type="message_stop"),
        ]
    )
    provider._client = SimpleNamespace(messages=messages_api)
    history = [
        Message(role="user", content="第一轮"),
        Message(role="assistant", content="上一条回复"),
        Message(role="user", content="第二轮"),
    ]

    events = asyncio.run(collect(provider.stream(history)))

    assert events == [StreamEvent(text="你好"), StreamEvent(done=True)]
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

    events = asyncio.run(collect(provider.stream([])))

    assert len(events) == 1
    assert isinstance(events[0].err, RuntimeError)
    assert str(events[0].err) == "anthropic unavailable"
    assert events[0].done is False


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

    events = asyncio.run(collect(provider.stream(history)))

    assert events == [
        StreamEvent(text="Hello"),
        StreamEvent(text="!"),
        StreamEvent(done=True),
    ]
    assert completions.params == {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "第一轮"},
            {"role": "assistant", "content": "上一条回复"},
        ],
        "stream": True,
    }


def test_openai_emits_error_event_instead_of_raising() -> None:
    provider = OpenAIProvider(openai_config())
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=FailingOpenAICompletions())
    )

    events = asyncio.run(collect(provider.stream([])))

    assert len(events) == 1
    assert isinstance(events[0].err, RuntimeError)
    assert str(events[0].err) == "openai unavailable"
    assert events[0].done is False
