"""Provider 对 Request 缓存通道与 reminder 注入的回归测试。"""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from Arkcode.config import ProviderConfig
from Arkcode.llm import Message, Request, StreamEnd, System, TextDelta
from Arkcode.llm.anthropic_provider import AnthropicProvider
from Arkcode.llm.openai_provider import OpenAIProvider
from Arkcode.tool import ToolDefinition


async def collect(events: AsyncIterator[object]) -> list[object]:
    return [event async for event in events]


class FakeAnthropicStream:
    async def __aenter__(self) -> "FakeAnthropicStream":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[Any]:
        async def iterate() -> AsyncIterator[Any]:
            yield SimpleNamespace(
                type="content_block_delta",
                index=0,
                delta=SimpleNamespace(type="text_delta", text="ok"),
            )

        return iterate()

    async def get_final_message(self) -> Any:
        return SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=12,
                output_tokens=4,
                cache_creation_input_tokens=8,
                cache_read_input_tokens=6,
            ),
        )


class FakeAnthropicMessages:
    params: dict[str, Any]

    def stream(self, **params: Any) -> FakeAnthropicStream:
        self.params = params
        return FakeAnthropicStream()


class FakeAnthropicStreamWithoutCache(FakeAnthropicStream):
    async def get_final_message(self) -> Any:
        return SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=3, output_tokens=1),
        )


class FakeAnthropicMessagesWithoutCache:
    def stream(self, **params: Any) -> FakeAnthropicStreamWithoutCache:
        self.params = params
        return FakeAnthropicStreamWithoutCache()


class FakeOpenAIStream:
    def __aiter__(self) -> AsyncIterator[Any]:
        async def iterate() -> AsyncIterator[Any]:
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        delta=SimpleNamespace(content="ok", tool_calls=[]),
                    )
                ],
                usage=None,
            )
            yield SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=2,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=7),
                ),
            )

        return iterate()


class FakeOpenAICompletions:
    async def create(self, **params: Any) -> FakeOpenAIStream:
        self.params = params
        return FakeOpenAIStream()


class FakeOpenAIStreamWithoutCache:
    def __aiter__(self) -> AsyncIterator[Any]:
        async def iterate() -> AsyncIterator[Any]:
            yield SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
            )

        return iterate()


class FakeOpenAICompletionsWithoutCache:
    async def create(self, **params: Any) -> FakeOpenAIStreamWithoutCache:
        self.params = params
        return FakeOpenAIStreamWithoutCache()


def anthro_config() -> ProviderConfig:
    return ProviderConfig("Claude", "anthropic", "secret", "test-model")


def openai_config() -> ProviderConfig:
    return ProviderConfig("GPT", "openai", "secret", "test-model")


def request() -> Request:
    return Request(
        messages=[Message(role="user", content="hello")],
        tools=[ToolDefinition("read_file", "read", {"type": "object"})],
        system=System(stable="stable", environment="Environment:\nDate: today"),
        reminder="<system-reminder>\nplan\n</system-reminder>",
    )


def test_anthropic_separates_cacheable_system_and_injects_reminder() -> None:
    provider = AnthropicProvider(anthro_config())
    messages = FakeAnthropicMessages()
    provider._client = SimpleNamespace(messages=messages)

    events = asyncio.run(collect(provider.stream(request())))

    assert messages.params["system"] == [
        {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "Environment:\nDate: today"},
    ]
    assert messages.params["messages"][-1]["content"][-1]["text"].startswith(
        "<system-reminder>"
    )
    assert events == [TextDelta("ok"), StreamEnd("end_turn", 12, 4, 6, 8, 8)]


def test_openai_puts_stable_prefix_before_environment_and_parses_cache_read() -> None:
    provider = OpenAIProvider(openai_config())
    completions = FakeOpenAICompletions()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    events = asyncio.run(collect(provider.stream(request())))

    assert completions.params["messages"] == [
        {"role": "system", "content": "stable\n\nEnvironment:\nDate: today"},
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "<system-reminder>\nplan\n</system-reminder>"},
    ]
    assert events == [TextDelta("ok"), StreamEnd("stop", 10, 2, 7)]


def test_missing_provider_cache_fields_default_to_zero() -> None:
    anthropic_provider = AnthropicProvider(anthro_config())
    anthropic_provider._client = SimpleNamespace(
        messages=FakeAnthropicMessagesWithoutCache()
    )
    openai_provider = OpenAIProvider(openai_config())
    openai_provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeOpenAICompletionsWithoutCache())
    )

    anthropic_events = asyncio.run(collect(anthropic_provider.stream(request())))
    openai_events = asyncio.run(collect(openai_provider.stream(request())))

    assert anthropic_events[-1] == StreamEnd("end_turn", 3, 1)
    assert openai_events[-1] == StreamEnd("unknown", 3, 1)
