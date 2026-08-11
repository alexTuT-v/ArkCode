"""/resume 命令：恢复历史会话。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_resume(context: CommandContext) -> None:
    context.session.open_resume()


RESUME_COMMAND = Command(
    "resume",
    "恢复历史会话",
    CommandKind.UI,
    handle_resume,
)
