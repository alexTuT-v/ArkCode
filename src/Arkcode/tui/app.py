"""ArkCode 的 Textual 应用与会话状态机。"""

import asyncio
import os
import time
from enum import Enum

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import Key
from textual.message import Message as TextualMessage
from textual.timer import Timer
from textual.widgets import OptionList, RichLog, Static, TextArea

from ..agent import ApprovalRequest
from ..config import ProviderConfig
from ..conversation import Conversation
from ..llm import Provider, new_provider
from ..mcp import McpStatus
from ..permission import Engine, Mode, Outcome
from ..prompt import EXECUTE_DIRECTIVE, render_banner
from ..tool import Registry
from .select import provider_options
from .stream import StreamControllerMixin, ToolDisplay
from .view import (
    approval_block,
    error_block,
    mcp_status_line,
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
    APPROVING = "approving"


def next_mode(mode: Mode) -> Mode:
    """按 UI 展示顺序循环到下一档权限模式。"""

    return Mode((int(mode) + 1) % len(Mode))


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
        Binding("escape", "cancel_turn", "Cancel", priority=True),
        Binding("shift+tab", "cycle_mode", "Mode", priority=True),
    ]

    def __init__(
        self,
        providers: list[ProviderConfig],
        version: str,
        registry: Registry,
        engine: Engine | None = None,
        mcp_status: McpStatus | None = None,
    ) -> None:
        super().__init__()
        self.providers = providers
        self._version = version
        # Textual 的 App 已占用 ``_registry`` 管理 DOM 节点。
        self._tool_registry = registry
        self.engine = engine
        self.mcp_status = mcp_status
        self.state = (
            SessionState.IDLE if len(providers) == 1 else SessionState.SELECTING
        )
        self.provider: Provider | None = None
        self.conv = Conversation()
        self.cur_reply = ""
        self.turn_start = 0.0
        self._stream_task: asyncio.Task[None] | None = None
        self._timer: Timer | None = None
        self.mode = engine.start_mode() if engine is not None else Mode.DEFAULT
        self.pending: ApprovalRequest | None = None
        self.approve_cursor = 0
        self.iter = 0
        self.usage_in = 0
        self.usage_out = 0
        self.usage_cache_read = 0
        self.usage_cache_creation = 0
        self.cur_thinking = ""
        self.cur_tools: list[ToolDisplay] = []
        self.turn_cancel: asyncio.Event | None = None

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
        log = self.query_one("#log", RichLog)
        log.write(render_banner(self._version, os.getcwd()))
        if self.mcp_status is not None:
            summary = mcp_status_line(self.mcp_status)
            if summary is not None:
                log.write(summary)
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

    def on_key(self, event: Key) -> None:
        if self.state is not SessionState.APPROVING:
            return
        if event.key in {"escape", "ctrl+c"}:
            return
        event.prevent_default()
        event.stop()
        self.update_approving(event.key)

    async def submit(self, text: str) -> None:
        """提交一轮用户输入；流式期间忽略新的提交。"""

        if self.state is not SessionState.IDLE:
            return
        command = text.strip()
        if command == "/exit":
            await self.action_quit()
            return
        if not command:
            return

        input_box = self.query_one("#input", MessageInput)
        input_box.clear()
        if command == "/plan":
            self.mode = Mode.PLAN
            self.query_one("#log", RichLog).write(
                Text("已进入计划模式（只读工具）", style="dim")
            )
            self._update_statusbar()
            return

        if command == "/do":
            self.mode = Mode.DEFAULT
            user_text = EXECUTE_DIRECTIVE
            self._update_statusbar()
        else:
            user_text = text

        self.conv.add_user(user_text)
        self.query_one("#log", RichLog).write(user_block(user_text))
        input_box.disabled = True
        self.cur_reply = ""
        self.cur_thinking = ""
        self.cur_tools = []
        self.iter = 0
        self.turn_cancel = asyncio.Event()
        self.turn_start = time.monotonic()
        self.state = SessionState.STREAMING
        self._refresh_streaming_view()
        self._stream_task = asyncio.create_task(self._consume_agent_events())
        self._timer = self.set_interval(0.1, self._tick)

    def _tick(self) -> None:
        if self.state in (SessionState.STREAMING, SessionState.APPROVING):
            self._refresh_streaming_view()

    def _elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.turn_start)

    def _refresh_streaming_view(self) -> None:
        if self.state is SessionState.APPROVING and self.pending is not None:
            self.query_one("#streaming", Static).update(
                approval_block(self.pending, self.approve_cursor)
            )
            return
        self.query_one("#streaming", Static).update(
            streaming_block(
                self.cur_reply,
                int(self._elapsed()),
                self.cur_tools,
                self.iter,
                self.cur_thinking,
            )
        )

    async def _wait_for_streaming_refresh(self) -> None:
        await self.query_one("#streaming", Static).wait_for_refresh()

    def _finish_with_assistant(self, reply: str) -> None:
        elapsed = self._elapsed()
        self.query_one("#log", RichLog).write(render_markdown(reply, elapsed))
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
        self.cur_thinking = ""
        self.cur_tools = []
        self.iter = 0
        self.turn_cancel = None
        self.pending = None
        self.approve_cursor = 0
        self.state = SessionState.IDLE
        self.query_one("#streaming", Static).update("")
        input_box = self.query_one("#input", MessageInput)
        input_box.disabled = False
        input_box.focus()
        self._update_statusbar()

    def _update_statusbar(self) -> None:
        if self.provider is not None:
            self.query_one("#statusbar", Static).update(
                status_bar(
                    self.provider,
                    self.mode,
                    self.usage_in,
                    self.usage_out,
                    self.usage_cache_read,
                    self.usage_cache_creation,
                )
            )

    async def action_quit(self) -> None:
        if self.state in (SessionState.STREAMING, SessionState.APPROVING):
            self._cancel_active_turn()
            return
        self.exit()

    def action_cancel_turn(self) -> None:
        if self.state in (SessionState.STREAMING, SessionState.APPROVING):
            self._cancel_active_turn()

    def _cancel_active_turn(self) -> None:
        if self.pending is not None and not self.pending.respond.done():
            self.pending.respond.set_result(Outcome.DENY_ONCE)
        if self.turn_cancel is not None:
            self.turn_cancel.set()

    def action_cycle_mode(self) -> None:
        if self.state is not SessionState.IDLE:
            return
        self.mode = next_mode(self.mode)
        self.query_one("#log", RichLog).write(
            Text(f"已切换到 {self.mode} 模式", style="dim")
        )
        self._update_statusbar()


def new_app(
    providers: list[ProviderConfig],
    version: str,
    registry: Registry,
    engine: Engine,
    mcp_status: McpStatus | None = None,
) -> ArkCodeApp:
    """构造注入权限引擎的 TUI 应用。"""

    return ArkCodeApp(providers, version, registry, engine, mcp_status)
