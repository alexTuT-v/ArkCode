"""Slash 命令分发控制。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...commands import CommandContext, dispatch, parse
from ..adapters.command_ui import CommandUIAdapter

if TYPE_CHECKING:
    from ..app import ArkCodeApp


class CommandController:
    """解析 Slash 输入、构造端口上下文并执行统一分发。"""

    def __init__(self, app: ArkCodeApp, ui: CommandUIAdapter) -> None:
        self._app = app
        self._ui = ui

    async def dispatch(self, text: str) -> bool:
        name, args, is_slash = parse(text)
        if not is_slash:
            return False
        shown = text.strip()
        if name == "":
            if shown == "/":
                self._ui.println("未知命令：输入 /help 查看可用命令")
            else:
                self._ui.println(f"未知命令: {shown}，输入 /help 查看可用命令")
            return True
        context = CommandContext(
            args=args,
            session=self._ui,
            skills=self._ui,
            status=self._ui,
            ui=self._ui,
            sandbox=self._ui,
        )
        handled = await dispatch(self._app.cmd_registry, name, context)
        if not handled:
            self._ui.println(f"未知命令: {shown}，输入 /help 查看可用命令")
            return True
        await self._ui.drain()
        return True
