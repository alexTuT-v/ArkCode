"""人在回路批准菜单渲染。"""

from rich.text import Text

from ...agents import ApprovalRequest


def approval_block(request: ApprovalRequest, cursor: int = 0) -> Text:
    """渲染人在回路的三选一批准菜单。"""

    choices = (
        "1. 允许本次",
        "2. 永久允许（写入本地配置）",
        "3. 拒绝本次",
    )
    block = Text()
    block.append(f"● {request.name}\n", style="bold cyan")
    block.append(f"  {request.args}\n", style="bold")
    block.append(f"  {request.reason}\n", style="dim")
    block.append("是否继续?\n")
    for index, choice in enumerate(choices):
        selected = index == cursor
        block.append(
            ("> " if selected else "  ") + choice + "\n",
            style="reverse bold" if selected else "",
        )
    block.append("↑↓ 选择 · 回车确认 · Esc 取消", style="dim")
    return block
