"""StreamingHost 到 ArkCodeApp 展示层的适配实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import RenderableType
from textual.widgets import RichLog, Static

from ...agents import ApprovalRequest, Usage
from ..state import SessionState
from ..views.approvals import approval_block
from ..views.messages import error_block, streaming_block
from ..widgets.message_input import MessageInput
from ..widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from ..app import ArkCodeApp


class StreamingHostApp:
    """把 StreamingController 的宿主协议映射到 App 的展示层。"""

    def __init__(self, app: ArkCodeApp) -> None:
        self._app = app

    def write_log(self, renderable: RenderableType) -> None:
        self._app.query_one("#log", RichLog).write(renderable)

    async def wait_for_streaming_refresh(self) -> None:
        await self._app.query_one("#streaming", Static).wait_for_refresh()

    def refresh_streaming_view(self) -> None:
        app = self._app
        if app.state is SessionState.APPROVING and app.pending is not None:
            app.query_one("#streaming", Static).update(
                approval_block(app.pending, app.approve_cursor)
            )
            return
        app.query_one("#streaming", Static).update(
            streaming_block(
                app.cur_reply,
                int(app._elapsed()),
                app.cur_tools,
                app.iter,
                app.cur_thinking,
            )
        )

    def finish_turn(self) -> None:
        app = self._app
        if app._timer is not None:
            app._timer.stop()
        app._timer = None
        app._stream_task = None
        app.streaming.reset()
        app.pending = None
        app.approve_cursor = 0
        app.state = SessionState.IDLE
        app.query_one("#streaming", Static).update("")
        input_box = app.query_one("#input", MessageInput)
        input_box.disabled = False
        input_box.focus()
        app.update_statusbar()

    def finish_with_error(self, error: Exception) -> None:
        app = self._app
        message = str(error)
        for provider in app.providers:
            message = message.replace(provider.api_key, "[REDACTED]")
        app.query_one("#log", RichLog).write(error_block(message, app._elapsed()))
        self.finish_turn()

    def update_usage(self, usage: Usage) -> None:
        app = self._app
        app.usage_in += usage.input
        app.usage_out += usage.output
        app.usage_cache_read += usage.cache_read
        app.usage_cache_creation += usage.cache_creation
        app.update_statusbar()

    def set_approval(self, request: ApprovalRequest) -> None:
        app = self._app
        app.pending = request
        app.approve_cursor = 0
        app.state = SessionState.APPROVING
        app.refresh_streaming_view()

    def elapsed(self) -> float:
        return self._app._elapsed()

    def status_bar(self) -> StatusBar:
        return self._app.query_one("#statusbar", StatusBar)
