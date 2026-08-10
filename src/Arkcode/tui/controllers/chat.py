"""聊天输入控制：普通文本进入会话流，Slash 交给命令分发。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from ..state import SessionState
from ..views.messages import user_block
from ..widgets.message_input import MessageInput

if TYPE_CHECKING:
    from ...application import SessionService
    from ..app import ArkCodeApp
    from .commands import CommandController


class ChatController:
    def __init__(
        self,
        app: ArkCodeApp,
        session: SessionService,
        commands: CommandController,
    ) -> None:
        self._app = app
        self._session = session
        self._commands = commands

    async def submit(self, text: str) -> None:
        """提交一轮用户输入；流式期间忽略新的提交。"""

        command = text.strip()
        if not command:
            return
        if await self._commands.dispatch(command):
            input_box = self._app.query_one("#input", MessageInput)
            input_box.clear()
            self._app.completion.hide()
            self._app.render_completion()
            return
        if self._app.state is not SessionState.IDLE:
            return
        input_box = self._app.query_one("#input", MessageInput)
        input_box.clear()
        await self.submit_user_text(text)

    async def submit_user_text(
        self,
        user_text: str,
        *,
        display_text: str | None = None,
    ) -> None:
        """把普通用户文本写入会话并启动 Agent 消费任务。"""

        input_box = self._app.query_one("#input", MessageInput)
        self._app.write_log(user_block(display_text or user_text))
        input_box.disabled = True
        self._app.streaming.reset()
        self._app.turn_start = time.monotonic()
        self._app.state = SessionState.STREAMING
        self._app.refresh_streaming_view()
        self._app._stream_task = asyncio.create_task(
            self._app.streaming.consume(self._session.submit_message(user_text))
        )
        self._app._timer = self._app.set_interval(0.1, self._app._tick)
