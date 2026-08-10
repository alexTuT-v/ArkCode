"""/plan 命令：切换到计划模式（只读工具）。"""

from __future__ import annotations

from ...permissions import Mode
from ..models import Command, CommandContext, CommandKind


async def handle_plan(context: CommandContext) -> None:
    context.session.set_mode(Mode.PLAN)
    context.ui.println("已进入计划模式（只读工具）")


PLAN_COMMAND = Command(
    "plan",
    "切换到计划模式",
    CommandKind.UI,
    handle_plan,
)
