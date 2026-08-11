"""Pane worker：单次 chdir、mailbox 消费、idle 与 Plan 审批。"""

import asyncio
from pathlib import Path

import pytest

from Arkcode.teams.mailbox import Box
from Arkcode.teams.models import MessageType
from Arkcode.teams.protocol import new_message
from Arkcode.teams.worker import TeamMemberLoop, run_team_member


class StubAgent:
    def __init__(self, plan_text: str = "计划内容") -> None:
        self.plan_text = plan_text
        self.runs: list[tuple[str, object]] = []

    async def run_to_completion(self, conv, task, mode, cancel):
        self.runs.append((task, mode))
        from Arkcode.agents.events import RunResult, RunStatus, Usage

        return RunResult(
            status=RunStatus.COMPLETED,
            final_text=self.plan_text,
            error=None,
            usage=Usage(),
            tool_count=1,
            last_activity="read_file",
        )


class FakeTeamManager:
    def __init__(self) -> None:
        self.active: dict[str, bool] = {}

    async def set_member_active(self, team, member, active) -> None:
        self.active[member] = active


def make_loop(
    tmp_path: Path,
    *,
    plan_mode: bool = False,
) -> tuple[TeamMemberLoop, Box, FakeTeamManager, StubAgent]:
    box = Box(tmp_path / "team")
    agent = StubAgent()
    manager = FakeTeamManager()
    from Arkcode.conversations import Conversation

    loop = TeamMemberLoop(
        member_name="alice",
        agent_id="agent-alice",
        team_name="demo",
        lead_agent_id="lead",
        box=box,
        agent=agent,  # type: ignore[arg-type]
        conversation=Conversation(),
        team_manager=manager,  # type: ignore[arg-type]
        plan_mode_required=plan_mode,
        mailbox_dir=tmp_path / "team" / "mailbox",
    )
    return loop, box, manager, agent


@pytest.mark.asyncio
async def test_loop_consumes_mailbox_and_notifies_idle(tmp_path: Path) -> None:
    loop, box, manager, _ = make_loop(tmp_path)
    await box.write("agent-alice", new_message("lead", "写 README"))

    async def stop_after_idle() -> None:
        while True:
            messages = await box.read("lead")
            if (
                any("[idle] alice" in message.text for message in messages)
                and manager.active.get("alice") is False
            ):
                loop._mailbox_dir = tmp_path / "gone"
                loop.wake()
                return
            await asyncio.sleep(0.02)

    task = asyncio.create_task(stop_after_idle())
    await asyncio.wait_for(loop.run(), 5.0)
    task.cancel()
    assert loop.turns == 1
    assert manager.active["alice"] is False
    lead_messages = await box.read("lead")
    assert any("[idle] alice" in message.text for message in lead_messages)


@pytest.mark.asyncio
async def test_plan_approval_flow(tmp_path: Path) -> None:
    loop, box, manager, _ = make_loop(tmp_path, plan_mode=True)
    await box.write("agent-alice", new_message("lead", "先做计划"))
    done = asyncio.Event()

    async def approve() -> None:
        while True:
            lead_messages = await box.read("lead")
            request = next(
                (
                    message
                    for message in lead_messages
                    if message.type is MessageType.PLAN_APPROVAL_REQUEST
                ),
                None,
            )
            if request is not None:
                await box.write(
                    "agent-alice",
                    new_message(
                        "lead",
                        "批准",
                        message_type=MessageType.PLAN_APPROVAL_RESPONSE,
                        request_id=request.request_id,
                        approve=True,
                    ),
                )
                done.set()
                return
            await asyncio.sleep(0.02)

    approver = asyncio.create_task(approve())
    loop._mailbox_dir = None
    try:
        await asyncio.wait_for(loop.run(), 5.0)
    except Exception:
        pass
    await asyncio.wait_for(done.wait(), 5.0)
    approver.cancel()
    assert loop.turns == 2


@pytest.mark.asyncio
async def test_shutdown_request_exits(tmp_path: Path) -> None:
    loop, box, manager, _ = make_loop(tmp_path)
    await box.write(
        "agent-alice",
        new_message(
            "lead",
            "收工",
            message_type=MessageType.SHUTDOWN_REQUEST,
            request_id="req-1",
        ),
    )
    loop._mailbox_dir = None
    exit_code = await asyncio.wait_for(loop.run(), 5.0)
    assert exit_code == 0
    lead_messages = await box.read("lead")
    assert any(
        message.type is MessageType.SHUTDOWN_RESPONSE
        for message in lead_messages
    )


def test_run_team_member_chdirs_once(monkeypatch, tmp_path: Path) -> None:
    worktree_dir = tmp_path / "wt"
    worktree_dir.mkdir()
    calls: list[str] = []
    import os

    original_chdir = os.chdir

    def spy_chdir(path: object) -> None:
        calls.append(str(path))
        original_chdir(path)

    monkeypatch.setattr("os.chdir", spy_chdir)

    class Args:
        team = "demo"
        member = "alice"
        agent_id = "agent-alice"
        session_dir = str(tmp_path / "s")
        worktree = str(worktree_dir)
        agent_type = "general-purpose"
        model = ""
        plan_mode = False

    class FakeLoop:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def run(self) -> int:
            return 0

    asyncio.run(run_team_member(Args(), loop_factory=FakeLoop))
    assert calls == [str(worktree_dir.resolve())]


def test_run_team_member_validates_required_args(monkeypatch) -> None:
    class Args:
        team = ""
        member = ""
        agent_id = ""
        session_dir = ""
        worktree = ""

    code = asyncio.run(run_team_member(Args(), loop_factory=object))
    assert code == 2
