"""/do 命令：执行已确认的计划。"""

from __future__ import annotations

from ...permissions import Mode
from ...prompts import EXECUTE_DIRECTIVE
from ..models import Command, CommandContext, CommandKind


async def handle_do(context: CommandContext) -> None:
    context.session.set_mode(Mode.DEFAULT)
    context.session.submit_prompt("/do", EXECUTE_DIRECTIVE)


DO_COMMAND = Command(
    "do",
    "执行已确认的计划",
    CommandKind.PROMPT,
    handle_do,
)
