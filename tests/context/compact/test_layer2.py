from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Arkcode.context import ManageInput, TriggerKind
from Arkcode.context.state import (
    CompactCircuitBreaker,
    RecoveryState,
    new_session_context,
)
from Arkcode.context.summary import (
    _join_after_summary,
    group_by_user_turn,
    pick_recent_tail,
    run_summary,
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
    ToolCall,
    ToolResult,
)


class ScriptedProvider:
    name = "fake"
    model = "fake"

    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.requests: list[Request] = []

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        for event in self.scripts[len(self.requests) - 1]:
            yield event


def make_input(
    tmp_path: Path,
    provider: ScriptedProvider,
    messages: list[Message],
    *,
    trigger: TriggerKind = TriggerKind.MANUAL,
) -> ManageInput:
    conv = Conversation()
    conv.replace_history(messages)
    return ManageInput(
        conv=conv,
        provider=provider,
        model="fake",
        context_window=200000,
        tool_defs=[],
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(tmp_path)),
        usage_anchor=0,
        anchor_msg_len=0,
        estimated_token=1000,
        trigger=trigger,
    )


def test_recent_tail_requires_both_token_and_message_lower_bounds() -> None:
    messages = [Message(role="user", content="x" * 9000) for _ in range(6)]

    recent = pick_recent_tail(messages)

    assert len(recent) == 5


def test_recent_tail_never_starts_with_orphan_tool_result() -> None:
    messages = [
        Message(role="user", content="old"),
        Message(
            role="assistant",
            tool_calls=[ToolCall("id", "read_file", "{}")],
        ),
        Message(role="tool", tool_results=[ToolResult("id", "x" * 35000)]),
        Message(role="assistant", content="done"),
        Message(role="user", content="next"),
        Message(role="assistant", content="ok"),
    ]

    recent = pick_recent_tail(messages)

    assert recent[0].role == "assistant"
    assert recent[0].tool_calls[0].id == "id"


def test_join_after_summary_avoids_consecutive_user_messages() -> None:
    joined = _join_after_summary(
        Message(role="user", content="summary"),
        [Message(role="user", content="recent")],
    )

    assert [message.role for message in joined] == ["user", "assistant", "user"]


def test_group_by_user_turn_keeps_each_assistant_tool_exchange_together() -> None:
    messages = [
        Message(role="user", content="u1"),
        Message(role="assistant", content="a1"),
        Message(role="tool"),
        Message(role="user", content="u2"),
        Message(role="assistant", content="a2"),
    ]

    groups = group_by_user_turn(messages)

    assert [len(group) for group in groups] == [3, 2]


@pytest.mark.asyncio
async def test_run_summary_retries_ptl_by_dropping_oldest_user_groups(
    tmp_path: Path,
) -> None:
    ptl = PromptTooLongError("too long")
    provider = ScriptedProvider(
        [
            [StreamError(ptl)],
            [StreamError(ptl)],
            [StreamError(ptl)],
            [TextDelta("<summary>compressed</summary>"), StreamEnd("stop")],
        ]
    )
    messages = [
        item
        for index in range(5)
        for item in (
            Message(role="user", content=f"user-{index}"),
            Message(role="assistant", content=f"assistant-{index}"),
        )
    ]

    result = await run_summary(make_input(tmp_path, provider, messages))

    assert len(provider.requests) == 4
    serialized = [request.messages[0].content for request in provider.requests]
    assert "user-0" in serialized[0]
    assert "user-0" not in serialized[1]
    assert "user-1" not in serialized[2]
    assert "user-2" not in serialized[3]
    assert result.messages[0].content.startswith("## 历史会话摘要\ncompressed")
    assert result.summary.startswith("## 历史会话摘要\ncompressed")
    assert result.messages[1:] == result.keep
    assert provider.requests[-1].tools is None


@pytest.mark.asyncio
async def test_run_summary_never_sends_empty_retry_request(tmp_path: Path) -> None:
    provider = ScriptedProvider([[StreamError(PromptTooLongError("too long"))]] * 3)
    messages = [Message(role="user", content="only")]

    with pytest.raises(PromptTooLongError):
        await run_summary(make_input(tmp_path, provider, messages))

    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_ptl_retry_switches_to_twenty_percent_group_drops(
    tmp_path: Path,
) -> None:
    ptl = StreamError(PromptTooLongError("too long"))
    provider = ScriptedProvider(
        [[ptl], [ptl], [ptl], [ptl], [TextDelta("<summary>ok</summary>")]]
    )
    messages = [
        item
        for index in range(10)
        for item in (
            Message(role="user", content=f"u-{index}"),
            Message(role="assistant", content=f"a-{index}"),
        )
    ]

    await run_summary(make_input(tmp_path, provider, messages))

    group_counts = [
        sum(f"user: u-{index}" in request.messages[0].content for index in range(10))
        for request in provider.requests
    ]
    assert group_counts == [10, 9, 8, 7, 5]
