"""ArkCode 的 Textual 应用与会话状态机。"""

import asyncio
import os
import time
from enum import Enum

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message as TextualMessage
from textual.timer import Timer
from textual.widgets import OptionList, RichLog, Static, TextArea

from .. import __version__
from ..config import ProviderConfig
from ..conversation import Conversation
from ..llm import Provider, new_provider
from ..prompt import render_banner
from .select import provider_options
from .stream import StreamControllerMixin
from .view import (
    error_block,
    render_markdown,
    status_bar,
    streaming_block,
    user_block,
)


class SessionState(Enum):
    """当前会话所处的交互阶段。"""

    SELECTING = "selecting"
    IDLE = "idle"
    STREAMING = "streaming"


class MessageInput(TextArea):
    """Enter 提交、Alt+Enter 换行的多行输入框。"""

    BINDINGS = [
        Binding("enter", "submit_message", "Submit", priority=True),
        Binding("alt+enter", "insert_newline", "New line", priority=True),
    ]

    class Submitted(TextualMessage):
        """输入框提交事件。"""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def action_submit_message(self) -> None:
        self.post_message(self.Submitted(self.text))

    def action_insert_newline(self) -> None:
        self.insert("\n")


class ArkCodeApp(StreamControllerMixin, App[None]):
    """多协议 LLM 终端对话客户端。"""

    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }

    #provider-select {
        width: 70%;
        height: auto;
        max-height: 70%;
        margin: 2 4;
        border: round $accent;
    }

    #log {
        width: 1fr;
        height: 1fr;
        min-width: 0;
        padding: 1 2;
    }

    #streaming {
        width: 1fr;
        height: auto;
        max-height: 40%;
        padding: 0 2;
    }

    #input-row {
        width: 1fr;
        height: auto;
        min-height: 3;
        max-height: 8;
        border-top: solid $accent;
    }

    #prompt {
        width: 3;
        height: 3;
        padding: 0 0 0 1;
        color: $accent;
        background: transparent;
    }

    #input {
        width: 1fr;
        height: auto;
        min-height: 3;
        max-height: 8;
        border: none;
    }

    #statusbar {
        width: 1fr;
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
    ]

    def __init__(self, providers: list[ProviderConfig]) -> None:
        super().__init__()
        self.providers = providers
        self.state = (
            SessionState.IDLE if len(providers) == 1 else SessionState.SELECTING
        )
        self.provider: Provider | None = None
        self.conv = Conversation()
        self.cur_reply = ""
        self.turn_start = 0.0
        self._stream_task: asyncio.Task[None] | None = None
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        if len(self.providers) > 1:
            yield OptionList(
                *provider_options(self.providers),
                id="provider-select",
            )
        yield RichLog(id="log", wrap=True, markup=True, min_width=1)
        yield Static("", id="streaming")
        with Horizontal(id="input-row"):
            yield Static("❯", id="prompt")
            yield MessageInput(
                id="input",
                soft_wrap=True,
                placeholder="Send a message...",
            )
        yield Static("", id="statusbar")

    def on_mount(self) -> None:
        self.query_one("#log", RichLog).write(render_banner(__version__, os.getcwd()))
        if len(self.providers) == 1:
            self._activate_provider(self.providers[0])
            return
        self._show_selection()

    def _show_selection(self) -> None:
        self.state = SessionState.SELECTING
        for selector in (
            "#log",
            "#streaming",
            "#input-row",
            "#input",
            "#prompt",
            "#statusbar",
        ):
            self.query_one(selector).display = False
        self.query_one("#provider-select", OptionList).focus()

    def _activate_provider(self, config: ProviderConfig) -> None:
        self.provider = new_provider(config)
        self.state = SessionState.IDLE
        option_list = self.query("#provider-select")
        if option_list:
            option_list.first().display = False
        for selector in (
            "#log",
            "#streaming",
            "#input-row",
            "#input",
            "#prompt",
            "#statusbar",
        ):
            self.query_one(selector).display = True
        self._update_statusbar()
        self.query_one("#input", MessageInput).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._activate_provider(self.providers[event.option_index])

    async def on_message_input_submitted(self, event: MessageInput.Submitted) -> None:
        await self.submit(event.text)

    async def submit(self, text: str) -> None:
        """提交一轮用户输入；流式期间忽略新的提交。"""

        if self.state is not SessionState.IDLE:
            return
        if text.strip() == "/exit":
            await self.action_quit()
            return
        if not text.strip():
            return

        self.conv.add_user(text)
        self.query_one("#log", RichLog).write(user_block(text))
        input_box = self.query_one("#input", MessageInput)
        input_box.clear()
        input_box.disabled = True
        self.cur_reply = ""
        self.turn_start = time.monotonic()
        self.state = SessionState.STREAMING
        self._refresh_streaming_view()
        self._stream_task = asyncio.create_task(self._consume_stream())
        self._timer = self.set_interval(0.1, self._tick)

    def _tick(self) -> None:
        if self.state is SessionState.STREAMING:
            self._refresh_streaming_view()

    def _elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.turn_start)

    def _refresh_streaming_view(self) -> None:
        self.query_one("#streaming", Static).update(
            streaming_block(self.cur_reply, int(self._elapsed()))
        )

    async def _wait_for_streaming_refresh(self) -> None:
        await self.query_one("#streaming", Static).wait_for_refresh()

    def _finish_with_assistant(self, reply: str) -> None:
        elapsed = self._elapsed()
        self.query_one("#log", RichLog).write(render_markdown(reply, elapsed))
        self.conv.add_assistant(reply)
        self._finish_turn()

    def _finish_with_error(self, error: Exception) -> None:
        message = str(error)
        for provider in self.providers:
            message = message.replace(provider.api_key, "[REDACTED]")
        self.query_one("#log", RichLog).write(error_block(message, self._elapsed()))
        self._finish_turn()

    def _finish_turn(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = None
        self._stream_task = None
        self.cur_reply = ""
        self.state = SessionState.IDLE
        self.query_one("#streaming", Static).update("")
        input_box = self.query_one("#input", MessageInput)
        input_box.disabled = False
        input_box.focus()

    def _update_statusbar(self) -> None:
        if self.provider is not None:
            self.query_one("#statusbar", Static).update(status_bar(self.provider))

    async def action_quit(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()
        self.exit()
