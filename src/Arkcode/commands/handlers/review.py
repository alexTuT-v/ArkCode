"""/review 命令：请求审查当前上下文。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind

REVIEW_DIRECTIVE = (
    "请审查当前上下文中的代码变更和已读取文件，指出潜在 bug、"
    "可读性问题和可以简化的地方。"
)


async def handle_review(context: CommandContext) -> None:
    context.session.submit_prompt("/review", REVIEW_DIRECTIVE)


REVIEW_COMMAND = Command(
    "review",
    "请求审查当前上下文",
    CommandKind.PROMPT,
    handle_review,
)
