"""命令系统四端口到 ArkCodeApp 的适配层。"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text

from ...agents import CompactEvent, CompactPhase
from ...commands import (
    CommandUI,
    McpServerInfo,
    SandboxCommands,
    SessionCommands,
    SkillCommands,
    StatusQueries,
    WorktreeCommands,
)
from ...commands.models import SandboxStatus
from ...permissions import Mode
from ...sessions import (
    SessionInfo,
    list_sessions,
)
from ...sessions import (
    delete_session as delete_session_dir,
)
from ...tools.workspace import ExecutionPathContext
from ..state import SessionState
from ..views.messages import error_block, format_compact_notice

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from ...application import SessionService
    from ..app import ArkCodeApp


class CommandUIAdapter(
    CommandUI,
    SessionCommands,
    SkillCommands,
    StatusQueries,
    SandboxCommands,
    WorktreeCommands,
):
    """把命令所需的四类能力映射到 ArkCodeApp 与会话服务。"""

    def __init__(self, app: ArkCodeApp, session: SessionService) -> None:
        self._app = app
        self._session = session
        self._tasks: list[Awaitable[None]] = []

    async def drain(self) -> None:
        for task in self._tasks:
            await task
        self._tasks.clear()

    # ---- CommandUI ----

    def println(self, message: str) -> None:
        self._app.write_log(Text(message, style="dim"))

    def error(self, message: str) -> None:
        self._app.write_log(error_block(message, 0))

    def request_exit(self) -> None:
        self._session.close()
        self._app.exit()

    # ---- SessionCommands ----

    def mode(self) -> Mode:
        return self._session.mode

    def set_mode(self, mode: Mode) -> None:
        self._session.set_mode(mode)
        self._app.update_statusbar()

    def idle(self) -> bool:
        return self._app.state is SessionState.IDLE

    def submit_prompt(self, label: str, prompt: str) -> None:
        self._tasks.append(self._app.chat.submit_user_text(prompt, display_text=label))

    def force_compact(self) -> None:
        self._tasks.append(self._force_compact())

    async def _force_compact(self) -> None:
        try:
            before, after = await self._session.force_compact()
            event = CompactEvent(CompactPhase.AFTER_AUTO, before=before, after=after)
        except Exception as error:
            event = CompactEvent(CompactPhase.AFTER_AUTO, err=error)
        self.println(format_compact_notice(event))

    def open_resume(self) -> None:
        self._app.sessions.begin_resume()

    def clear_session(self) -> None:
        self._session.clear_session()
        self._app.usage_in = 0
        self._app.usage_out = 0
        self._app.usage_cache_read = 0
        self._app.usage_cache_creation = 0
        self._app.clear_log()

    def resume_by_id(self, session_id: str) -> bool:
        info = next(
            (
                item
                for item in list_sessions(self._session.sessions_dir)
                if item.id == session_id
            ),
            None,
        )
        if info is None:
            return False
        asyncio.create_task(self._app.sessions.resume(info))
        return True

    def delete_session(self, session_id: str) -> bool:
        return delete_session_dir(self._session.sessions_dir, session_id)

    def clear_memory(self) -> None:
        self._session.clear_memory()

    # ---- SkillCommands ----

    def list_skills(self) -> list[tuple[str, str, str]]:
        return self._app.skills.list_skills()

    def skill_info(self, name: str) -> str | None:
        return self._app.skills.skill_info(name)

    def reload_skills(self) -> None:
        self._app.skills.reload_skills()

    async def invoke_skill(self, name: str, args: str) -> None:
        await self._app.skills.invoke_skill(name, args)

    # ---- StatusQueries ----

    def usage(self) -> tuple[int, int]:
        return self._app.usage_in, self._app.usage_out

    def model_name(self) -> str:
        provider = self._session.provider
        return provider.model if provider is not None else ""

    def cwd(self) -> str:
        return str(self._app.workspace)

    def tool_count(self) -> int:
        return self._app.tool_registry.count()

    def memory_files(self) -> list[str]:
        if self._app.mem_mgr is None:
            return []
        project, user = self._app.mem_mgr.list_files()
        return project + user

    def session_path(self) -> str:
        return self._session.journal.path

    def session_id(self) -> str:
        return self._session.runtime.session.session_id

    def session_list(self) -> list[SessionInfo]:
        return list_sessions(self._session.sessions_dir)

    def memory_dirs(self) -> tuple[str, str]:
        manager = self._app.mem_mgr
        if manager is None:
            return "", ""
        return manager.dirs()

    def mcp_server_status(self) -> list[McpServerInfo]:
        manager = self._app.mcp_manager
        if manager is None:
            return []
        return [
            McpServerInfo(
                name=status.name,
                tool_count=status.tool_count,
                connected=status.connected,
                error=status.error,
            )
            for status in manager.server_summary()
        ]

    # ---- SandboxCommands ----

    def status(self) -> SandboxStatus:
        engine = self._session.permissions
        bash = self._app.tool_registry.get("bash")
        sandbox = getattr(bash, "sandbox", None) if bash else None
        enabled = engine.sandbox_enabled if engine is not None else False
        return SandboxStatus(
            enabled=enabled,
            auto_allow=enabled,
            backend=type(sandbox).__name__ if sandbox else "",
            available=sandbox.available() if sandbox else False,
        )

    def enable(self, auto_allow: bool) -> str | None:
        from ...sandbox import SandboxConfig, create_sandbox

        bash = self._app.tool_registry.get("bash")
        if bash is None:
            return "错误: 未找到 Bash 工具"
        sandbox = getattr(bash, "sandbox", None)
        if sandbox is None:
            sandbox = create_sandbox()
            if sandbox is None:
                return "错误: 当前系统不支持沙箱（仅支持 macOS / Linux）"
        if not sandbox.available():
            return f"错误: 沙箱后端 {type(sandbox).__name__} 不可用，请安装对应工具"
        workspace = Path(self._app.workspace)
        config = SandboxConfig(
            allow_write=[str(workspace), tempfile.gettempdir()],
            deny_write=[
                str(workspace / ".Arkcode" / "config.yaml"),
                str(workspace / ".Arkcode" / "permissions.local.yaml"),
                str(workspace / ".Arkcode" / "skills"),
            ],
            network_enabled=False,
        )
        setattr(bash, "sandbox", sandbox)
        setattr(bash, "sandbox_config", config)
        engine = self._session.permissions
        if engine is not None:
            engine.sandbox_enabled = auto_allow
        return None

    def disable(self) -> None:
        bash = self._app.tool_registry.get("bash")
        if bash is not None:
            setattr(bash, "sandbox", None)
            setattr(bash, "sandbox_config", None)
        engine = self._session.permissions
        if engine is not None:
            engine.sandbox_enabled = False

    # ---- WorktreeCommands ----

    async def create_worktree(self, slug: str) -> str:
        manager = getattr(self._app, "worktree_manager", None)
        if manager is None:
            return "错误: Worktree 功能未启用"
        worktree = await manager.create(slug, "HEAD", manual=True)
        return f"已创建 Worktree: {worktree.path}（分支 {worktree.branch}）"

    def list_worktrees(self) -> list[tuple[str, str, str, bool]]:
        manager = getattr(self._app, "worktree_manager", None)
        if manager is None:
            return []
        current = manager.current_session
        return [
            (
                worktree.name,
                str(worktree.path),
                worktree.branch,
                current is not None and current.worktree_name == worktree.name,
            )
            for worktree in manager.list()
        ]

    async def enter_worktree(self, slug: str) -> str:
        manager = getattr(self._app, "worktree_manager", None)
        if manager is None:
            return "错误: Worktree 功能未启用"
        session = await manager.enter(slug)
        self._session.set_active_workspace(
            ExecutionPathContext.at(session.worktree_path)
        )
        return f"已进入 Worktree: {session.worktree_name}（进程 cwd 未改变）"

    async def exit_worktree(self, *, remove: bool, discard: bool) -> str:
        manager = getattr(self._app, "worktree_manager", None)
        if manager is None:
            return "错误: Worktree 功能未启用"
        current = manager.current_session
        if current is None:
            return "当前不在任何 Worktree 中"
        from ...worktrees import ExitAction, ExitOptions

        report = await manager.exit(
            current.worktree_name,
            ExitAction.REMOVE if remove else ExitAction.KEEP,
            ExitOptions(discard_changes=discard),
        )
        self._session.set_active_workspace(None)
        if report.removed:
            return f"已退出并删除 Worktree {current.worktree_name}"
        return f"已退出 Worktree {current.worktree_name}（保留）"

    async def remove_worktree(self, slug: str, *, discard: bool) -> str:
        manager = getattr(self._app, "worktree_manager", None)
        if manager is None:
            return "错误: Worktree 功能未启用"
        from ...worktrees import ExitOptions

        report = await manager.remove(slug, ExitOptions(discard_changes=discard))
        if report.removed:
            return f"已删除 Worktree {slug}"
        return f"Worktree {slug} 未删除"
