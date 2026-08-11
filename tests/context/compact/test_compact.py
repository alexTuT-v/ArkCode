from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Arkcode.context import (
    CompactCircuitBreaker,
    ManageInput,
    RecoveryState,
    TriggerKind,
    manage_context,
    new_session_context,
)
from Arkcode.conversations import Conversation
from Arkcode.llm import Message, Request, StreamEnd, StreamEvent, TextDelta, ToolResult


class SummaryProvider:
    name = "fake"
    model = "fake"

    def __init__(self) -> None:
        self.requests: list[Request] = []

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        yield TextDelta("<summary>small</summary>")
        yield StreamEnd("stop")


def make_input(
    tmp_path: Path,
    *,
    estimated: int,
    trigger: TriggerKind,
    messages: list[Message] | None = None,
) -> tuple[ManageInput, SummaryProvider]:
    provider = SummaryProvider()
    conv = Conversation()
    conv.replace_history(messages or [Message(role="user", content="hello")])
    in_ = ManageInput(
        conv=conv,
        provider=provider,
        model="fake",
        context_window=200000,
        tool_defs=[],
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(tmp_path)),
        usage_anchor=estimated,
        anchor_msg_len=len(conv.messages()),
        estimated_token=estimated,
        trigger=trigger,
    )
    return in_, provider


@pytest.mark.asyncio
async def test_auto_below_threshold_does_not_replace_history(tmp_path: Path) -> None:
    in_, provider = make_input(tmp_path, estimated=1000, trigger=TriggerKind.AUTO)
    before = in_.conv.messages()

    output = await manage_context(in_)

    assert output.compaction is None
    assert in_.conv.messages() == before
    assert provider.requests == []
    assert output.before_tokens == 1000
    assert output.after_tokens == 1000


@pytest.mark.asyncio
async def test_auto_above_threshold_returns_structured_compaction(
    tmp_path: Path,
) -> None:
    in_, _ = make_input(tmp_path, estimated=180000, trigger=TriggerKind.AUTO)
    before = in_.conv.messages()

    output = await manage_context(in_)

    assert output.compaction is not None
    assert output.compaction.summary.startswith("## 历史会话摘要\nsmall")
    assert "## 边界提示" in output.compaction.summary
    assert in_.conv.messages() == before


@pytest.mark.asyncio
async def test_auto_compaction_result_contains_matching_messages(
    tmp_path: Path,
) -> None:
    in_, _ = make_input(tmp_path, estimated=180000, trigger=TriggerKind.AUTO)

    output = await manage_context(in_)

    assert output.compaction is not None
    assert output.compaction.messages[0].content == output.compaction.summary
    assert output.compaction.messages[1:] == output.compaction.keep


@pytest.mark.asyncio
async def test_manual_runs_summary_below_threshold(tmp_path: Path) -> None:
    in_, provider = make_input(tmp_path, estimated=500, trigger=TriggerKind.MANUAL)
    before = in_.conv.messages()

    output = await manage_context(in_)

    assert len(provider.requests) == 1
    assert output.compaction is not None
    assert in_.conv.messages() == before


@pytest.mark.asyncio
async def test_emergency_ignores_breaker_and_returns_compaction(tmp_path: Path) -> None:
    messages = [
        Message(
            role="tool",
            tool_results=[ToolResult("large", "x" * 60000)],
        )
    ]
    in_, provider = make_input(
        tmp_path,
        estimated=180000,
        trigger=TriggerKind.EMERGENCY,
        messages=messages,
    )
    for _ in range(3):
        in_.auto_tracking.record_failure()

    output = await manage_context(in_)

    assert len(provider.requests) == 1
    assert output.compaction is not None
    assert in_.conv.messages() == messages


@pytest.mark.asyncio
async def test_manual_compact_ignores_tripped_auto_breaker(tmp_path: Path) -> None:
    in_, provider = make_input(tmp_path, estimated=500, trigger=TriggerKind.MANUAL)
    for _ in range(3):
        in_.auto_tracking.record_failure()

    output = await manage_context(in_)

    assert len(provider.requests) == 1
    assert output.compaction is not None
