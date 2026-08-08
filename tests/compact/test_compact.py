from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Arkcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Arkcode.compact.compact import ManageInput, TriggerKind, manage_context
from Arkcode.conversation import Conversation
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
        replacement=ContentReplacementState(),
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
async def test_auto_below_threshold_only_applies_layer1(tmp_path: Path) -> None:
    in_, provider = make_input(tmp_path, estimated=1000, trigger=TriggerKind.AUTO)

    output = await manage_context(in_)

    assert provider.requests == []
    assert output.before_tokens == 1000
    assert output.after_tokens == 1000


@pytest.mark.asyncio
async def test_auto_above_threshold_runs_summary(tmp_path: Path) -> None:
    in_, provider = make_input(tmp_path, estimated=180000, trigger=TriggerKind.AUTO)

    output = await manage_context(in_)

    assert len(provider.requests) == 1
    assert output.before_tokens == 180000
    assert in_.conv.messages()[0].content.startswith("## 历史会话摘要")


@pytest.mark.asyncio
async def test_manual_runs_summary_below_threshold(tmp_path: Path) -> None:
    in_, provider = make_input(tmp_path, estimated=500, trigger=TriggerKind.MANUAL)

    await manage_context(in_)

    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_emergency_offloads_before_summary_and_ignores_breaker(
    tmp_path: Path,
) -> None:
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

    await manage_context(in_)

    assert len(provider.requests) == 1
    assert (Path(in_.session.spill_dir) / "large").stat().st_size == 60000


@pytest.mark.asyncio
async def test_auto_threshold_uses_smaller_layer1_history_even_when_anchor_includes_it(
    tmp_path: Path,
) -> None:
    messages = [
        Message(
            role="tool",
            tool_results=[ToolResult("large", "x" * 60000)],
        )
    ]
    in_, provider = make_input(
        tmp_path,
        estimated=18000,
        trigger=TriggerKind.AUTO,
        messages=messages,
    )
    in_.context_window = 40000

    output = await manage_context(in_)

    assert provider.requests == []
    assert output.after_tokens < 7000
    assert "[content offloaded]" in in_.conv.messages()[0].tool_results[0].content


@pytest.mark.asyncio
async def test_manual_compact_ignores_tripped_auto_breaker(tmp_path: Path) -> None:
    in_, provider = make_input(tmp_path, estimated=500, trigger=TriggerKind.MANUAL)
    for _ in range(3):
        in_.auto_tracking.record_failure()

    await manage_context(in_)

    assert len(provider.requests) == 1
