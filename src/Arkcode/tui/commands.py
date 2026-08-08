"""Slash Command 与 Textual App 之间的适配层。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import RichLog

from ..agent import CompactEvent, CompactPhase
from ..command import UI, Kind, parse
from ..compact import new_session_context
from ..conversation import Conversation
from ..permission import Mode
from ..session import Writer
from .resume import begin_resume
from .view import error_block

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from .app import ArkCodeApp


def format_compact_notice(event: CompactEvent) -> str:
    if event.phase is CompactPhase.BEFORE_AUTO:
        return "正在压缩上下文..."
    if event.phase is CompactPhase.BEFORE_EMERGENCY:
        return "上下文撞墙，自动压缩中..."
    if event.err is not None:
        return f"压缩失败：{event.err}"
    return f"已压缩，token 从 {event.before} 降至 {event.after}"


class AppUI(UI):
    """把命令所需能力映射到 ArkCodeApp。"""

    def __init__(self, app: ArkCodeApp) -> None:
        self.app = app
        self.tasks: list[Awaitable[None]] = []

    async def drain(self) -> None:
        for task in self.tasks:
            await task

    def println(self, message: str) -> None:
        self.app.query_one("#log", RichLog).write(Text(message, style="dim"))

    def error(self, message: str) -> None:
        self.app.query_one("#log", RichLog).write(error_block(message, 0))

    def mode(self) -> Mode:
        return self.app.mode

    def set_mode(self, mode: Mode) -> None:
        self.app.mode = mode
        self.app._update_statusbar()

    def inject_and_send(self, label: str, prompt: str) -> None:
        self.tasks.append(self.app._submit_user_text(prompt, display_text=label))

    def usage_in(self) -> int:
        return self.app.usage_in

    def usage_out(self) -> int:
        return self.app.usage_out

    def model_name(self) -> str:
        return self.app.provider.model if self.app.provider is not None else ""

    def cwd(self) -> str:
        return str(self.app.workspace)

    def tool_count(self) -> int:
        return self.app._tool_registry.count()

    def memory_files(self) -> list[str]:
        if self.app.mem_mgr is None:
            return []
        project, user = self.app.mem_mgr.list_files()
        return project + user

    def session_path(self) -> str:
        return self.app.writer.path

    def session_id(self) -> str:
        return self.app.runtime.session.session_id

    def quit(self) -> None:
        self.app.writer.close()
        self.app.exit()

    def force_compact(self) -> None:
        self.tasks.append(self._force_compact())

    async def _force_compact(self) -> None:
        agent = self.app.agent
        if agent is None:
            self.error("压缩失败：尚未选择 provider")
            return
        definitions = (
            self.app._tool_registry.read_only_definitions()
            if self.app.mode is Mode.PLAN
            else self.app._tool_registry.definitions()
        )
        try:
            before, after = await agent.run_force_compact(self.app.conv, definitions)
            event = CompactEvent(CompactPhase.AFTER_AUTO, before=before, after=after)
        except Exception as error:
            event = CompactEvent(CompactPhase.AFTER_AUTO, err=error)
        self.println(format_compact_notice(event))

    def open_resume_menu(self) -> None:
        begin_resume(self.app)

    def clear_and_new_session(self) -> None:
        context = new_session_context(str(self.app.workspace))
        writer = Writer(context.session_dir)
        if self.app.provider is not None:
            writer.set_model(self.app.provider.model)
        conversation = Conversation(
            on_append=writer.on_append,
            on_replace=writer.on_replace,
        )
        previous = self.app.writer
        self.app.writer = writer
        self.app.conv = conversation
        self.app.runtime.reset_for_new_session(context)
        self.app.usage_in = 0
        self.app.usage_out = 0
        self.app.usage_cache_read = 0
        self.app.usage_cache_creation = 0
        self.app.query_one("#log", RichLog).clear()
        self.clear_active_skills()
        previous.close()

    def idle(self) -> bool:
        return self.app.state is type(self.app.state).IDLE

    def skill_list(self) -> list[tuple[str, str, str]]:
        return [
            (
                name,
                description,
                self.app.skill_loader.get_source_label(name) or "unknown",
            )
            for name, description in self.app.skill_loader.get_catalog()
        ]

    def skill_info(self, name: str) -> str | None:
        skill = self.app.skill_loader.get(name)
        if skill is None:
            return None
        source = self.app.skill_loader.get_source_label(skill.name) or "unknown"
        model = skill.model or "default"
        directory = str(skill.is_directory).lower()
        return "\n".join(
            (
                f"name: {skill.name}",
                f"description: {skill.description}",
                f"mode: {skill.mode}",
                f"model: {model}",
                f"context: {skill.context}",
                f"source: {source}",
                f"path: {skill.source_path}",
                f"directory: {directory}",
            )
        )

    def reload_skills(self) -> None:
        self.app.skill_loader.reload()
        self.app._refresh_skill_integration()

    def append_system_message(self, name: str, result: str) -> None:
        content = (
            f"<system-reminder>\nSkill '{name}' result:\n{result}\n</system-reminder>"
        )
        self.app.conv.add_user(content)
        self.app.query_one("#log", RichLog).write(
            Text(f"[{name}] {result}", style="dim")
        )

    def clear_active_skills(self) -> None:
        if self.app.agent is not None:
            self.app.agent.clear_active_skills()

    def track_skill_task(self, task: asyncio.Task[None]) -> None:
        self.app.track_skill_task(task)


async def dispatch_slash(app: ArkCodeApp, text: str) -> bool:
    name, args, is_slash = parse(text)
    if not is_slash:
        return False
    command = app.cmd_registry.lookup(name)
    ui = AppUI(app)
    if command is None:
        shown = text.strip()
        prefix = f"未知命令: {shown}，" if shown not in {"", "/"} else "未知命令："
        ui.println(prefix + "输入 /help 查看可用命令")
        return True
    if command.kind in {Kind.UI, Kind.PROMPT} and not ui.idle():
        ui.error("请等待当前任务完成")
        return True
    try:
        await command.handler(ui, args)
        await ui.drain()
    except Exception as error:
        ui.error(str(error))
    return True
