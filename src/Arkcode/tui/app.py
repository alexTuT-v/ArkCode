"""ArkCode 的 Textual 应用与会话状态机。"""

import asyncio
import os
import time
from enum import Enum
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import Key
from textual.message import Message as TextualMessage
from textual.timer import Timer
from textual.widgets import OptionList, RichLog, Static, TextArea

from ..agent import Agent, ApprovalRequest, SessionRuntime
from ..command import Registry as CommandRegistry
from ..command import register_builtins
from ..compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from ..config import ProviderConfig, effective_context_window
from ..conversation import Conversation
from ..llm import Provider, new_provider
from ..mcp import McpStatus
from ..memory import Manager as MemoryManager
from ..permission import Engine, Mode, Outcome
from ..prompt import render_banner
from ..session import Writer
from ..tool import Registry
from .commands import dispatch_slash
from .complete import CompletionMenu
from .resume import SessionItem, begin_resume, do_resume_session, handle_resume_key
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
    RESUMING = "resuming"


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

    #resume-list {
        width: 90%;
        height: auto;
        max-height: 70%;
        margin: 1 4;
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

    #completion {
        width: 1fr;
        height: auto;
        max-height: 10;
        padding: 0 4;
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
        runtime: SessionRuntime | None = None,
        writer: Writer | None = None,
        mem_mgr: MemoryManager | None = None,
        instruction_text: str = "",
        memory_text: str = "",
        sessions_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.providers = providers
        self._version = version
        # Textual 的 App 已占用 ``_registry`` 管理 DOM 节点。
        self._tool_registry = registry
        self.cmd_registry = CommandRegistry()
        register_builtins(self.cmd_registry)
        self.completion = CompletionMenu()
        self.engine = engine
        self.runtime = runtime or SessionRuntime(
            replacement=ContentReplacementState(),
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context(os.getcwd()),
        )
        self.agent: Agent | None = None
        self._pending_command = ""
        self.mcp_status = mcp_status
        self.state = (
            SessionState.IDLE if len(providers) == 1 else SessionState.SELECTING
        )
        self.provider: Provider | None = None
        self.writer = writer or Writer(self.runtime.session.session_dir)
        self.mem_mgr = mem_mgr
        self.instruction_text = instruction_text
        self.memory_text = memory_text
        self.sessions_dir = sessions_dir or str(
            Path(self.runtime.session.session_dir).parent
        )
        self.conv = Conversation(
            on_append=self.writer.on_append,
            on_replace=self.writer.on_replace,
        )
        self.resume_list: OptionList
        self.resume_items: list[SessionItem] = []
        self.resume_filtered: list[SessionItem] = []
        self.resume_query = ""
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
        yield OptionList(id="resume-list")
        yield RichLog(id="log", wrap=True, markup=True, min_width=1)
        yield Static("", id="streaming")
        with Horizontal(id="input-row"):
            yield Static("❯", id="prompt")
            yield MessageInput(
                id="input",
                soft_wrap=True,
                placeholder="Send a message...",
            )
        yield Static("", id="completion")
        yield Static("", id="statusbar")

    def on_mount(self) -> None:
        self.resume_list = self.query_one("#resume-list", OptionList)
        self.resume_list.display = False
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

    def on_unmount(self) -> None:
        self.writer.close()

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
        self.writer.set_model(self.provider.model)
        if self.mem_mgr is not None:
            self.mem_mgr.set_provider(self.provider, self.provider.model)
        self.runtime.context_window = effective_context_window(config)
        self.agent = Agent(
            self.provider,
            self._tool_registry,
            self._version,
            self.engine,
            runtime=self.runtime,
            memory_manager=self.mem_mgr,
            instruction_text=self.instruction_text,
            memory_text=self.memory_text,
        )
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

    async def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option_list.id == "resume-list":
            if self.state is SessionState.RESUMING and event.option_index < len(
                self.resume_filtered
            ):
                await do_resume_session(
                    self,
                    self.resume_filtered[event.option_index].info,
                )
            return
        self._activate_provider(self.providers[event.option_index])

    async def on_message_input_submitted(self, event: MessageInput.Submitted) -> None:
        if self.state is SessionState.IDLE and self.completion.active:
            selected = self.completion.selected()
            if selected is not None:
                input_box = self.query_one("#input", MessageInput)
                input_box.text = "/" + selected.name
                await self.submit(input_box.text)
                return
        await self.submit(event.text)

    async def on_key(self, event: Key) -> None:
        if self.state is SessionState.RESUMING:
            if event.key in {"escape", "backspace", "enter"} or getattr(
                event, "character", None
            ):
                await handle_resume_key(self, event)
            return
        if self.state is SessionState.IDLE and await self._handle_completion_key(event):
            return
        if self.state is not SessionState.APPROVING:
            return
        if event.key in {"escape", "ctrl+c"}:
            return
        event.prevent_default()
        event.stop()
        self.update_approving(event.key)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "input":
            return
        self.completion.update(event.text_area.text, self.cmd_registry)
        self._render_completion()

    def _render_completion(self) -> None:
        self.query_one("#completion", Static).update(
            self.completion.render(max(1, self.size.width - 8))
        )

    async def _handle_completion_key(self, event: Key) -> bool:
        if not self.completion.active:
            return False
        if event.key == "up":
            self.completion.move_up()
        elif event.key == "down":
            self.completion.move_down()
        elif event.key == "escape":
            self.completion.hide()
        elif event.key in {"enter", "tab"}:
            selected = self.completion.selected()
            if selected is not None:
                input_box = self.query_one("#input", MessageInput)
                input_box.text = "/" + selected.name
                await self.submit(input_box.text)
            elif event.key == "enter":
                input_box = self.query_one("#input", MessageInput)
                await self.submit(input_box.text)
            else:
                self.completion.hide()
        else:
            return False
        event.prevent_default()
        event.stop()
        self._render_completion()
        return True

    async def dispatch_slash(self, text: str) -> bool:
        return await dispatch_slash(self, text)

    def begin_resume(self) -> None:
        begin_resume(self)

    async def submit(self, text: str) -> None:
        """提交一轮用户输入；流式期间忽略新的提交。"""

        command = text.strip()
        if not command:
            return

        if await self.dispatch_slash(command):
            input_box = self.query_one("#input", MessageInput)
            input_box.clear()
            self.completion.hide()
            self._render_completion()
            return
        if self.state is not SessionState.IDLE:
            return

        input_box = self.query_one("#input", MessageInput)
        input_box.clear()
        await self._submit_user_text(text)

    async def _submit_user_text(
        self,
        user_text: str,
        *,
        display_text: str | None = None,
    ) -> None:
        """把普通用户文本写入会话并启动 Agent 消费任务。"""

        input_box = self.query_one("#input", MessageInput)
        self.conv.add_user(user_text)
        self.query_one("#log", RichLog).write(user_block(display_text or user_text))
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
        self.writer.close()
        self.exit()

    def action_cancel_turn(self) -> None:
        if self.state is SessionState.RESUMING:
            from .resume import cancel_resume

            cancel_resume(self)
            return
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
    runtime: SessionRuntime | None = None,
    writer: Writer | None = None,
    mem_mgr: MemoryManager | None = None,
    instruction_text: str = "",
    memory_text: str = "",
    sessions_dir: str | None = None,
) -> ArkCodeApp:
    """构造注入权限引擎的 TUI 应用。"""

    return ArkCodeApp(
        providers,
        version,
        registry,
        engine,
        mcp_status,
        runtime,
        writer,
        mem_mgr,
        instruction_text,
        memory_text,
        sessions_dir,
    )
