"""TUI 内置斜杠命令注册与压缩状态文案。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import RichLog

from ..agent import CompactEvent, CompactPhase
from ..permission import Mode
from ..prompt import EXECUTE_DIRECTIVE

if TYPE_CHECKING:
    from .app import ArkCodeApp

CommandHandler = Callable[["ArkCodeApp"], Awaitable[None]]


def format_compact_notice(event: CompactEvent) -> str:
    """把所有压缩路径格式化为统一、稳定的用户提示。"""

    if event.phase is CompactPhase.BEFORE_AUTO:
        return "正在压缩上下文..."
    if event.phase is CompactPhase.BEFORE_EMERGENCY:
        return "上下文撞墙，自动压缩中..."
    if event.err is not None:
        return f"压缩失败：{event.err}"
    return f"已压缩，token 从 {event.before} 降至 {event.after}"


async def handle_exit(app: ArkCodeApp) -> None:
    await app.action_quit()


async def handle_plan(app: ArkCodeApp) -> None:
    app.mode = Mode.PLAN
    app.query_one("#log", RichLog).write(
        Text("已进入计划模式（只读工具）", style="dim")
    )
    app._update_statusbar()


async def handle_do(app: ArkCodeApp) -> None:
    app.mode = Mode.DEFAULT
    app._update_statusbar()
    await app._submit_user_text(EXECUTE_DIRECTIVE)


async def handle_compact(app: ArkCodeApp) -> None:
    agent = app.agent
    if agent is None:
        app.query_one("#log", RichLog).write(
            Text("压缩失败：尚未选择 provider", style="dim")
        )
        return
    definitions = (
        app._tool_registry.read_only_definitions()
        if app.mode is Mode.PLAN
        else app._tool_registry.definitions()
    )
    try:
        before, after = await agent.run_force_compact(app.conv, definitions)
        event = CompactEvent(
            phase=CompactPhase.AFTER_AUTO,
            before=before,
            after=after,
        )
    except Exception as error:
        event = CompactEvent(phase=CompactPhase.AFTER_AUTO, err=error)
    app.query_one("#log", RichLog).write(
        Text(format_compact_notice(event), style="dim")
    )


async def handle_resume(app: ArkCodeApp) -> None:
    if app.state is not type(app.state).IDLE:
        app.query_one("#log", RichLog).write(Text("请等待当前任务完成", style="dim"))
        return
    app.begin_resume()


async def handle_unknown(app: ArkCodeApp) -> None:
    command = app._pending_command
    app.query_one("#log", RichLog).write(
        Text(
            f"未知命令: {command}，可用命令: /exit /plan /do /compact /resume",
            style="dim",
        )
    )


BUILTIN_COMMANDS: dict[str, CommandHandler] = {
    "/exit": handle_exit,
    "/plan": handle_plan,
    "/do": handle_do,
    "/compact": handle_compact,
    "/resume": handle_resume,
}


def dispatch_command(input_: str) -> tuple[CommandHandler | None, bool]:
    """识别命令；普通文本返回未处理标记。"""

    if not input_.startswith("/"):
        return None, False
    return BUILTIN_COMMANDS.get(input_, handle_unknown), True
