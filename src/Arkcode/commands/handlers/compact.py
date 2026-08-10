"""/compact 命令：立即压缩当前上下文。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_compact(context: CommandContext) -> None:
    context.session.force_compact()


COMPACT_COMMAND = Command(
    "compact",
    "立即压缩当前上下文",
    CommandKind.UI,
    handle_compact,
)
