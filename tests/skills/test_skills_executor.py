import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from Arkcode.agents import AgentEvent
from Arkcode.config import ProviderConfig
from Arkcode.conversations import Conversation
from Arkcode.llm import Message, Request, StreamEnd, TextDelta, ToolResult
from Arkcode.skills import SkillExecutor, SkillMeta
from Arkcode.tools import Registry, Result
from Arkcode.tools.base import Tool


class RecordingMainAgent:
    def __init__(self) -> None:
        self.activated: list[tuple[str, str]] = []
        self.runtime = object()

    def activate_skill(self, name: str, body: str) -> None:
        self.activated.append((name, body))


class NamedParams(BaseModel):
    pass


class NamedTool(Tool[NamedParams]):
    read_only = True
    params_model = NamedParams

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name

    def name(self) -> str:
        return self.tool_name

    def description(self) -> str:
        return self.tool_name

    async def execute(self, params: NamedParams) -> Result:
        raise AssertionError("not called")


class FakeProvider:
    def __init__(self, model: str) -> None:
        self.name = "fake"
        self.model = model
        self.requests: list[Request] = []

    async def stream(self, req: Request) -> AsyncIterator[Any]:
        self.requests.append(req)
        yield TextDelta("<summary>summary text</summary>")
        yield StreamEnd("end")


class RecordingForkAgent:
    instances: ClassVar[list["RecordingForkAgent"]] = []
    error: ClassVar[BaseException | None] = None

    def __init__(
        self,
        provider: FakeProvider,
        registry: Registry,
        version: str,
        engine: object | None,
        *,
        runtime: object,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.version = version
        self.engine = engine
        self.runtime = runtime
        self.run_conversation: Conversation | None = None
        self.__class__.instances.append(self)

    async def run(
        self,
        conv: Conversation,
        mode: object,
        cancel: asyncio.Event,
    ) -> AsyncIterator[AgentEvent]:
        self.run_conversation = conv
        if self.error is not None:
            raise self.error
        yield AgentEvent(text="fork ")
        yield AgentEvent(text="result")
        yield AgentEvent(done=True)


def skill(
    *,
    body: str = "Review $ARGUMENTS",
    mode: str = "fork",
    context: str = "none",
    model: str | None = None,
) -> SkillMeta:
    return SkillMeta(
        name="review",
        description="Review code",
        prompt_body=body,
        mode=mode,  # type: ignore[arg-type]
        context=context,  # type: ignore[arg-type]
        model=model,
    )


def make_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conversation: Conversation | None = None,
) -> tuple[SkillExecutor, RecordingMainAgent, list[ProviderConfig]]:
    import Arkcode.skills.executor as executor_module

    RecordingForkAgent.instances.clear()
    RecordingForkAgent.error = None
    configs: list[ProviderConfig] = []

    def provider_factory(config: ProviderConfig) -> FakeProvider:
        configs.append(config)
        return FakeProvider(config.model)

    monkeypatch.setattr(executor_module, "new_provider", provider_factory)
    monkeypatch.setattr(executor_module, "Agent", RecordingForkAgent)
    registry = Registry()
    registry.register(NamedTool("first"))  # type: ignore[arg-type]
    registry.register(NamedTool("LoadSkill"))  # type: ignore[arg-type]
    registry.register(NamedTool("last"))  # type: ignore[arg-type]
    main_agent = RecordingMainAgent()
    executor = SkillExecutor(
        main_agent,  # type: ignore[arg-type]
        conversation or Conversation(),
        ProviderConfig(
            name="fake", protocol="openai", api_key="secret", model="main-model"
        ),
        registry,
        None,
        "1.2.3",
        tmp_path,
    )
    return executor, main_agent, configs


@pytest.mark.parametrize(
    ("body", "args", "expected"),
    [
        ("Review all files", "src", "Review all files"),
        ("Review $ARGUMENTS", "src", "Review src"),
        ("$ARGUMENTS then $ARGUMENTS", "src", "src then src"),
    ],
)
def test_execute_inline_only_activates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    args: str,
    expected: str,
) -> None:
    conversation = Conversation()
    executor, agent, configs = make_executor(tmp_path, monkeypatch, conversation)

    executor.execute_inline(skill(body=body, mode="inline"), args)

    assert agent.activated == [("review", expected)]
    assert conversation.messages() == []
    assert configs == []


@pytest.mark.asyncio
async def test_fork_none_is_isolated_and_filters_system_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = Conversation()
    main.add_user("main history")
    before = main.messages()
    executor, _, configs = make_executor(tmp_path, monkeypatch, main)

    result = await executor.execute_fork(skill(model="fork-model"), "src")

    assert result == "fork result"
    assert main.messages() == before
    assert configs[0].model == "fork-model"
    child = RecordingForkAgent.instances[-1]
    assert child.run_conversation is not main
    assert child.runtime is not getattr(executor._agent, "runtime")
    assert child.run_conversation is not None
    assert child.run_conversation.messages() == [
        Message(role="user", content="Review src")
    ]
    assert [item.name for item in child.registry.definitions()] == ["first", "last"]
    assert executor._agent.activated == []


@pytest.mark.asyncio
async def test_fork_without_model_reuses_original_provider_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, _, configs = make_executor(tmp_path, monkeypatch)

    await executor.execute_fork(skill(model=None), "src")

    assert configs[0] is executor._provider_config
    assert configs[0].model == "main-model"


@pytest.mark.asyncio
async def test_fork_recent_copies_last_five_user_assistant_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = Conversation.from_messages(
        [
            Message(role="user", content="u1"),
            Message(role="assistant", content="a1"),
            Message(
                role="tool",
                tool_results=[ToolResult(tool_call_id="1", content="secret")],
            ),
            Message(role="user", content="u2"),
            Message(role="assistant", content="a2"),
            Message(role="user", content="u3"),
            Message(role="assistant", content="a3"),
        ]
    )
    executor, _, _ = make_executor(tmp_path, monkeypatch, main)

    await executor.execute_fork(skill(context="recent"), "src")

    messages = RecordingForkAgent.instances[-1].run_conversation.messages()  # type: ignore[union-attr]
    assert [(message.role, message.content) for message in messages] == [
        ("assistant", "a1"),
        ("user", "u2"),
        ("assistant", "a2"),
        ("user", "u3"),
        ("assistant", "a3"),
        ("user", "Review src"),
    ]


@pytest.mark.asyncio
async def test_fork_full_summarizes_history_without_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = Conversation()
    main.add_user("long history")
    executor, _, _ = make_executor(tmp_path, monkeypatch, main)

    await executor.execute_fork(skill(context="full"), "src")

    child = RecordingForkAgent.instances[-1]
    messages = child.run_conversation.messages()  # type: ignore[union-attr]
    assert messages[0].content == "## Previous conversation summary\nsummary text"
    assert messages[1].content == "Review src"
    assert child.provider.requests[0].tools is None


@pytest.mark.asyncio
async def test_fork_converts_normal_errors_to_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, _, _ = make_executor(tmp_path, monkeypatch)
    RecordingForkAgent.error = RuntimeError("boom")

    result = await executor.execute_fork(skill(), "src")

    assert result == "[skill review failed: boom]"


@pytest.mark.asyncio
async def test_fork_propagates_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, _, _ = make_executor(tmp_path, monkeypatch)
    RecordingForkAgent.error = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await executor.execute_fork(skill(), "src")
