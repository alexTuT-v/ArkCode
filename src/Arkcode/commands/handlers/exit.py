"""/exit 命令：退出 ArkCode。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_exit(context: CommandContext) -> None:
    context.ui.request_exit()


EXIT_COMMAND = Command(
    "exit",
    "退出 ArkCode",
    CommandKind.UI,
    handle_exit,
)
