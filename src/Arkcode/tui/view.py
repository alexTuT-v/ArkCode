"""TUI 中可复用的 Rich 渲染块。"""

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from ..llm import Provider


def user_block(message: str) -> Text:
    """渲染一条已提交的用户消息。"""

    return Text("● " + message, style="bold")


def render_markdown(reply: str, elapsed: float) -> RenderableType:
    """渲染完成的 Markdown 回复及总耗时。"""

    return Group(
        Text("●", style="bold cyan"),
        Markdown(reply),
        Text(f"Completed in {elapsed:.1f}s", style="dim"),
    )


def error_block(message: str, elapsed: float) -> Text:
    """渲染可区分且带耗时的错误消息。"""

    return Text(f"● {message}\nFailed after {elapsed:.1f}s", style="bold red")


def status_bar(provider: Provider) -> Table:
    """渲染左右对齐的 provider 名称与模型名。"""

    table = Table.grid(expand=True)
    table.add_column(justify="left", ratio=1)
    table.add_column(justify="right")
    table.add_row(provider.name, provider.model)
    return table


def streaming_block(reply: str, elapsed: int) -> Text:
    """渲染当前文本增量与实时计时。"""

    body = f"● {reply}\n" if reply else ""
    return Text(f"{body}Imagining… ({elapsed}s)")
