"""工具调用行与结果摘要渲染。"""

from rich.console import RenderableType
from rich.padding import Padding
from rich.text import Text


def tool_line(name: str, args: str) -> Text:
    """渲染 Claude Code 风格的工具调用行。"""

    text = Text("● ", style="bold cyan")
    text.append(f"{name}({args})", style="bold")
    return text


def tool_result_summary(result: str, is_error: bool) -> RenderableType:
    """渲染至多八行的缩进工具结果摘要。"""

    lines = result.splitlines()
    truncated = len(lines) > 8 or len(result) > 2000
    summary = "\n".join(lines[:8])
    if len(summary) > 2000:
        summary = summary[:2000]
    if truncated:
        summary = summary.rstrip() + "\n[truncated]"
    return Padding(
        Text("⎿ " + summary, style="red" if is_error else "dim"),
        (0, 0, 0, 2),
    )
