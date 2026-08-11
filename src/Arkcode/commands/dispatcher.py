"""Slash 命令的统一分发策略。"""

from __future__ import annotations

from .models import CommandContext, CommandKind
from .registry import CommandRegistry

BUSY_MESSAGE = "请等待当前任务完成"


async def dispatch(
    registry: CommandRegistry,
    name: str,
    context: CommandContext,
) -> bool:
    """分发已解析的命令名；未知命令返回 False，其余情况返回 True。"""

    command = registry.lookup(name)
    if command is None:
        return False
    if (
        command.kind in {CommandKind.UI, CommandKind.PROMPT}
        and not context.session.idle()
    ):
        context.ui.error(BUSY_MESSAGE)
        return True
    try:
        await command.handler(context)
    except Exception as error:
        context.ui.error(str(error))
    return True
