"""TUI 长生命周期后台消费者：Job 通知与 SubAgent 审批队列。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from rich.text import Text

from ..agents import ApprovalRequest
from ..subagents.approvals import ApprovalBroker
from ..subagents.manager import TaskManager
from ..subagents.notification import format_task_notification
from ..teams.mailbox import Box
from ..teams.models import Message
from .state import SessionState

if TYPE_CHECKING:
    from ..application import SessionService
    from .app import ArkCodeApp


async def consume_job_notifications(
    manager: TaskManager,
    session: SessionService,
) -> None:
    """消费 done 队列并把后台 Job 完成注入主 ReminderInbox。"""

    queue = manager.subscribe_done()
    while True:
        job_id = await queue.get()
        job = manager.get(job_id)
        if job is None or not job.run_in_background:
            continue
        session.append_reminder(format_task_notification(job))


async def consume_subagent_approvals(
    broker: ApprovalBroker,
    app: ArkCodeApp,
) -> None:
    """把子 Agent 审批转成主 TUI 的批准弹窗并等待响应。"""

    while True:
        record = await broker.next()
        translated = ApprovalRequest(
            name=record.tool_name,
            args=record.args_preview,
            reason=(
                f"[来自 SubAgent {record.agent_name or record.agent_id}] "
                f"{record.reason}"
            ),
            respond=record.respond,
            agent_id=record.agent_id,
            agent_name=record.agent_name,
            agent_type=record.agent_type,
            job_id=record.job_id,
            foreground=record.foreground,
        )
        previous_state = app.state
        app.pending = translated
        app.state = SessionState.APPROVING
        app.refresh_streaming_view()
        app.write_log(
            Text(
                f"[来自 SubAgent {record.agent_name or record.agent_id}] "
                f"等待审批: {record.tool_name} {record.args_preview}",
                style="yellow",
            )
        )
        try:
            while not record.respond.done():
                await asyncio.sleep(0.05)
        finally:
            if app.pending is translated:
                app.pending = None
            if app.state is SessionState.APPROVING:
                app.state = previous_state
            app.refresh_streaming_view()


def render_team_update(messages: list[Message]) -> str:
    """把 Lead 未读邮件渲染为 `<team-update>` reminder。"""

    lines: list[str] = []
    for index, message in enumerate(messages, 1):
        lines.append(
            f"[{index}] 来自 {message.from_agent}"
            f"(type={message.type.value},ts={message.timestamp}):"
        )
        lines.append("    " + message.text)
    body = "\n".join(lines)[:8000]
    return f"<team-update>\n{body}\n</team-update>"


async def consume_lead_mail(
    team_manager: Any,
    session: Any,
    event: asyncio.Event,
) -> None:
    """每秒轮询所有 Team 的 Lead mailbox，注入 reminder 并置位唤醒事件。"""

    while True:
        await asyncio.sleep(1.0)
        for team in team_manager.list():
            box = Box(team.config_dir)
            messages = await box.read("lead")
            unread_indexes = [
                index for index, message in enumerate(messages) if not message.read
            ]
            if not unread_indexes:
                continue
            unread = [messages[index] for index in unread_indexes]
            await box.mark_read("lead", unread_indexes)
            session.append_reminder(render_team_update(unread))
            event.set()
