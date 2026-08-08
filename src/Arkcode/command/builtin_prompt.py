"""向对话注入固定用户提示的命令。"""

from ..permission import Mode
from ..prompt import EXECUTE_DIRECTIVE
from .ui import UI

REVIEW_DIRECTIVE = (
    "请审查当前上下文中的代码变更和已读取文件，指出潜在 bug、"
    "可读性问题和可以简化的地方。"
)


async def handle_do(ui: UI, args: str) -> None:
    ui.set_mode(Mode.DEFAULT)
    ui.inject_and_send("/do", EXECUTE_DIRECTIVE)


async def handle_review(ui: UI, args: str) -> None:
    ui.inject_and_send("/review", REVIEW_DIRECTIVE)
