"""/clear 命令：清空当前会话并开启新会话。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_clear(context: CommandContext) -> None:
    context.session.clear_session()
    context.ui.println("已清空当前会话，开启新 session")


CLEAR_COMMAND = Command(
    "clear",
    "清空当前会话并开启新会话",
    CommandKind.UI,
    handle_clear,
)
