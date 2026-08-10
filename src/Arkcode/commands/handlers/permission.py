"""/permission 命令：显示当前权限模式。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_permission(context: CommandContext) -> None:
    context.ui.println(str(context.session.mode()))


PERMISSION_COMMAND = Command(
    "permission",
    "显示当前权限模式",
    CommandKind.LOCAL,
    handle_permission,
)
