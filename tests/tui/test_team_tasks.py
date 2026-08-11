"""TUI 后台消费者：Job 通知与 Lead 邮件唤醒。"""

import asyncio
from pathlib import Path

import pytest

from Arkcode.teams.mailbox import Box
from Arkcode.teams.protocol import new_message
from Arkcode.tui.tasks import consume_lead_mail, render_team_update


class FakeTeam:
    def __init__(self, box: Box) -> None:
        self.box = box
        self.config_dir = Path(box._directory).parent


class FakeTeamManager:
    def __init__(self, team: FakeTeam) -> None:
        self.teams = [team]

    def list(self):
        return self.teams


class FakeSession:
    def __init__(self) -> None:
        self.reminders: list[str] = []

    def append_reminder(self, text: str) -> None:
        self.reminders.append(text)


def test_render_team_update_format() -> None:
    from Arkcode.teams.models import MessageType

    message = new_message(
        "alice",
        "完成了任务",
        message_type=MessageType.PLAN_APPROVAL_REQUEST,
        request_id="req-1",
    )
    rendered = render_team_update([message])
    assert rendered.startswith("<team-update>")
    assert "来自 alice" in rendered
    assert "完成了任务" in rendered
    assert "</team-update>" in rendered
    assert len(rendered) <= 8000 + 40


@pytest.mark.asyncio
async def test_consume_lead_mail_injects_reminder_and_sets_event(
    tmp_path: Path,
) -> None:
    box = Box(tmp_path / "team")
    await box.write("lead", new_message("alice", "任务完成"))
    team = FakeTeam(box)
    manager = FakeTeamManager(team)
    session = FakeSession()
    event = asyncio.Event()

    task = asyncio.create_task(consume_lead_mail(manager, session, event))
    try:
        await asyncio.wait_for(event.wait(), 5.0)
        assert any("<team-update>" in item for item in session.reminders)
        messages = await box.read("lead")
        assert all(message.read for message in messages)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
