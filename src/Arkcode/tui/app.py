"""ArkCode 的 Textual 应用：组合、绑定与生命周期。"""

import asyncio
import time
from pathlib import Path

from rich.console import RenderableType
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import Key
from textual.timer import Timer
from textual.widgets import OptionList, RichLog, Static, TextArea

from ..agents import ApprovalRequest, SessionRuntime
from ..application import ApplicationRuntime, SessionService
from ..commands import CommandRegistry
from ..config import ProviderConfig
from ..mcp import Manager as McpManager
from ..mcp import McpStatus
from ..memory import Manager as MemoryManager
from ..permissions import Engine
from ..sessions import SessionJournal
from ..skills import SkillLoader
from ..tools import Registry, ToolSearchTool
from ..tools.skill_tools import InstallSkillTool, LoadSkillTool
from ..worktrees import WorktreeManager
from .adapters.command_ui import CommandUIAdapter
from .controllers.approvals import ApprovalController
from .controllers.chat import ChatController
from .controllers.commands import CommandController
from .controllers.completion import CompletionController
from .controllers.providers import ProviderController
from .controllers.sessions import SessionController, SessionItem
from .controllers.skills import SkillsController
from .state import AppStateMixin, SessionState, next_mode
from .streaming import StreamingController
from .streaming.host import StreamingHostApp
from .tasks import (
    consume_job_notifications,
    consume_lead_mail,
    consume_subagent_approvals,
)
from .views.banner import render_banner
from .views.status import mcp_status_line
from .widgets.completion import CompletionMenu
from .widgets.message_input import MessageInput
from .widgets.provider_select import provider_options
from .widgets.status_bar import StatusBar


class ArkCodeApp(AppStateMixin, App[None]):
    """多协议 LLM 终端对话客户端。"""

    CSS_PATH = "styles.tcss"

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
        journal: SessionJournal | None = None,
        mem_mgr: MemoryManager | None = None,
        instruction_text: str = "",
        memory_text: str = "",
        sessions_dir: str | None = None,
        workspace: str | Path | None = None,
        session: SessionService | None = None,
        mcp_manager: McpManager | None = None,
        worktree_manager: WorktreeManager | None = None,
        team_manager: object | None = None,
    ) -> None:
        super().__init__()
        self.providers = providers
        self._version = version
        if workspace is not None:
            self.workspace = Path(workspace).resolve()
        elif session is not None:
            self.workspace = session.workspace
        elif runtime is not None:
            self.workspace = Path(runtime.session.session_dir).resolve().parents[2]
        else:
            self.workspace = Path.cwd().resolve()
        # Textual 的 App 已占用 ``_registry`` 管理 DOM 节点。
        self._tool_registry = registry
        self.skill_loader = (
            session.skills if session is not None else SkillLoader(self.workspace)
        )
        self.skill_loader.load_all()
        self.session = session or SessionService(
            workspace=self.workspace,
            version=version,
            registry=self._tool_registry,
            permissions=engine,
            skills=self.skill_loader,
            memory=mem_mgr,
            instruction_text=instruction_text,
            memory_text=memory_text,
            sessions_dir=sessions_dir,
            runtime=runtime,
            journal=journal,
        )
        self.skills = SkillsController(self, self.session)
        self.load_skill_tool = LoadSkillTool(self.skill_loader)
        self._tool_registry.register(self.load_skill_tool)
        self._tool_registry.register(ToolSearchTool(self._tool_registry))
        self.install_skill_tool = InstallSkillTool(
            self.skill_loader,
            Path.home() / ".Arkcode" / "skills",
            self.skills.reload_skills,
        )
        self._tool_registry.register(self.install_skill_tool)
        self.cmd_registry = CommandRegistry()
        self.sessions = SessionController(self, self.session)
        self.approvals = ApprovalController(self)
        self.completions = CompletionController(self)
        self.adapter = CommandUIAdapter(self, self.session)
        self.commands = CommandController(self, self.adapter)
        self.chat = ChatController(self, self.session, self.commands)
        self.provider_controller = ProviderController(self, self.session)
        self.skills.rebuild()
        self.completion = CompletionMenu()
        self.mcp_status = mcp_status
        self.state = (
            SessionState.IDLE if len(providers) == 1 else SessionState.SELECTING
        )
        self.mem_mgr = mem_mgr
        self.mcp_manager = mcp_manager
        self.worktree_manager = worktree_manager
        self.team_manager = team_manager
        self.sessions_dir = sessions_dir or self.session.sessions_dir
        self.resume_list: OptionList
        self.resume_items: list[SessionItem] = []
        self.resume_filtered: list[SessionItem] = []
        self.resume_query = ""
        self._streaming_host = StreamingHostApp(self)
        self.streaming = StreamingController(self._streaming_host)
        self.turn_start = 0.0
        self._stream_task: asyncio.Task[None] | None = None
        self._timer: Timer | None = None
        self.pending: ApprovalRequest | None = None
        self.approve_cursor = 0
        self.usage_in = 0
        self.usage_out = 0
        self.usage_cache_read = 0
        self.usage_cache_creation = 0
        self._consumer_tasks: list[asyncio.Task[None]] = []
        self.lead_mail_event = asyncio.Event()
        if team_manager is None:
            team_manager = getattr(self.session, "team_manager", None)
        self.team_manager = team_manager

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
        yield StatusBar(id="statusbar")

    def on_mount(self) -> None:
        self.resume_list = self.query_one("#resume-list", OptionList)
        self.resume_list.display = False
        self.write_log(render_banner(self._version, str(self.workspace)))
        self._start_background_consumers()
        if self.mcp_status is not None:
            summary = mcp_status_line(self.mcp_status)
            if summary is not None:
                self.write_log(summary)
        if len(self.providers) == 1:
            self.provider_controller.activate(self.providers[0])
            return
        self.provider_controller.show_selection()

    def _start_background_consumers(self) -> None:
        manager = getattr(self.session, "task_manager", None)
        if manager is not None:
            self._consumer_tasks.append(
                asyncio.create_task(
                    consume_job_notifications(manager, self.session)
                )
            )
        broker = getattr(self.session, "approval_broker", None)
        if broker is not None:
            self._consumer_tasks.append(
                asyncio.create_task(consume_subagent_approvals(broker, self))
            )
        team_manager = getattr(self.session, "team_manager", None)
        if team_manager is not None:
            self._consumer_tasks.append(
                asyncio.create_task(
                    consume_lead_mail(
                        team_manager,
                        self.session,
                        self.lead_mail_event,
                    )
                )
            )
            self._consumer_tasks.append(
                asyncio.create_task(self._lead_mail_watcher())
            )

    async def _lead_mail_watcher(self) -> None:
        """Lead idle 时收到邮件自动发起一轮 autonomous turn。"""

        while True:
            await self.lead_mail_event.wait()
            self.lead_mail_event.clear()
            if self.state is SessionState.IDLE and self.provider is not None:
                await self.chat.submit_user_text(
                    "[team-update] 队员发来新消息，请按 Coordinator 流程处理，"
                    "汇总进展并决定下一步。",
                    display_text="[team-update]",
                )

    async def on_unmount(self) -> None:
        for task in self._consumer_tasks:
            task.cancel()
        if self._consumer_tasks:
            await asyncio.gather(*self._consumer_tasks, return_exceptions=True)
            self._consumer_tasks.clear()
        await self.session.shutdown()

    async def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option_list.id == "resume-list":
            if self.state is SessionState.RESUMING and event.option_index < len(
                self.resume_filtered
            ):
                await self.sessions.resume(
                    self.resume_filtered[event.option_index].info
                )
            return
        self.provider_controller.activate(self.providers[event.option_index])

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
                await self.sessions.handle_key(event)
            return
        if self.state is SessionState.IDLE and await self.completions.handle_key(event):
            return
        if self.state is not SessionState.APPROVING:
            return
        if event.key in {"escape", "ctrl+c"}:
            return
        event.prevent_default()
        event.stop()
        self.approvals.update(event.key)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "input":
            return
        self.completions.update_from_input(event.text_area.text)

    def render_completion(self) -> None:
        self.completions.render()

    async def submit(self, text: str) -> None:
        await self.chat.submit(text)

    async def dispatch_slash(self, text: str) -> bool:
        return await self.commands.dispatch(text)

    def clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def write_log(self, renderable: RenderableType) -> None:
        self.query_one("#log", RichLog).write(renderable)

    def _tick(self) -> None:
        if self.state in (SessionState.STREAMING, SessionState.APPROVING):
            self._streaming_host.refresh_streaming_view()

    def refresh_streaming_view(self) -> None:
        self._streaming_host.refresh_streaming_view()

    def _elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.turn_start)

    def update_statusbar(self) -> None:
        provider = self.provider
        if provider is not None:
            config = getattr(self.session, "_config", None)
            coordinator = False
            if config is not None:
                from ..teams.coordinator import is_enabled

                coordinator = is_enabled(config)
            self.query_one("#statusbar", StatusBar).set_status(
                provider,
                self.mode,
                self.usage_in,
                self.usage_out,
                self.usage_cache_read,
                self.usage_cache_creation,
                coordinator=coordinator,
            )

    async def action_quit(self) -> None:
        if self.state in (SessionState.STREAMING, SessionState.APPROVING):
            self._cancel_active_turn()
            return
        self.adapter.request_exit()

    def action_cancel_turn(self) -> None:
        if self.state is SessionState.RESUMING:
            self.sessions.cancel_resume()
            return
        if self.state in (SessionState.STREAMING, SessionState.APPROVING):
            manager = self.session.task_manager
            moved = (
                manager.move_foreground_to_background()
                if manager is not None
                else None
            )
            if moved is not None:
                self.write_log(
                    Text(
                        f"前台子 Agent Job {moved} 已切到后台，主对话可继续输入",
                        style="dim",
                    )
                )
                return
            self._cancel_active_turn()

    def _cancel_active_turn(self) -> None:
        self.approvals.cancel()
        self.session.cancel_turn()

    def action_cycle_mode(self) -> None:
        if self.state is not SessionState.IDLE:
            return
        self.mode = next_mode(self.mode)
        self.write_log(Text(f"已切换到 {self.mode} 模式", style="dim"))
        self.update_statusbar()


def new_app(runtime: ApplicationRuntime) -> ArkCodeApp:
    """构造注入权限引擎的 TUI 应用。"""

    return ArkCodeApp(
        runtime.config.providers,
        runtime.version,
        runtime.tools,
        runtime.permissions,
        mcp_status=runtime.mcp_status,
        mem_mgr=runtime.memory,
        session=runtime.session,
        workspace=runtime.workspace,
        mcp_manager=runtime.mcp,
        worktree_manager=runtime.worktree_manager,
        team_manager=runtime.team_manager,
    )
