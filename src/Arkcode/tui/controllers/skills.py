"""Skill 列表、信息、重载与动态命令注册。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.text import Text

from ...commands import (
    register_builtins,
    register_custom_commands,
    register_skill_commands,
    register_skill_management,
)
from ...prompts import render_skill_catalog

if TYPE_CHECKING:
    from ...application import SessionService
    from ..app import ArkCodeApp


class SkillsController:
    def __init__(self, app: ArkCodeApp, session: SessionService) -> None:
        self._app = app
        self._session = session

    def rebuild(self) -> None:
        """重建完整命令表（内置、管理命令与动态 Skill 命令）。"""

        registry = self._app.cmd_registry
        registry.clear()
        register_builtins(registry)
        register_custom_commands(registry, self._app.workspace)
        register_skill_management(registry, self._session.skills)
        if self._session.skill_executor is not None:
            register_skill_commands(
                registry,
                self._session.skills,
                self._session.skill_executor,
            )

    def register_dynamic_commands(self) -> None:
        executor = self._session.skill_executor
        if executor is not None:
            register_skill_commands(
                self._app.cmd_registry,
                self._session.skills,
                executor,
            )

    def reload_skills(self) -> None:
        """重载 Skill 目录并同步 Agent Catalog 与命令表。"""

        self._session.skills.reload()
        agent = self._session.agent
        if agent is not None:
            agent.set_skill_catalog(
                render_skill_catalog(self._session.skills.get_catalog())
            )
        self.rebuild()

    def list_skills(self) -> list[tuple[str, str, str]]:
        return [
            (
                name,
                description,
                self._session.skills.get_source_label(name) or "unknown",
            )
            for name, description in self._session.skills.get_catalog()
        ]

    def skill_info(self, name: str) -> str | None:
        skill = self._session.skills.get(name)
        if skill is None:
            return None
        source = self._session.skills.get_source_label(skill.name) or "unknown"
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

    async def invoke_skill(self, name: str, args: str) -> None:
        loader = self._session.skills
        executor = self._session.skill_executor
        current = loader.get(name)
        if current is None or executor is None:
            self._app.write_log(
                Text(
                    f"Unknown skill: {name}. Try /skill reload.",
                    style="bold red",
                )
            )
            return
        if current.mode == "inline":
            executor.execute_inline(current, args)
            trigger = f"/{name}" + (f" {args}" if args else "")
            await self._app.chat.submit_user_text(
                trigger,
                display_text=f"/{name}",
            )
            return

        async def run_fork() -> None:
            try:
                result = await executor.execute_fork(current, args)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                result = f"[skill {name} failed: {error}]"
            self.append_system_message(name, result)

        task = asyncio.create_task(run_fork())
        self.track_skill_task(task)

    def append_system_message(self, name: str, result: str) -> None:
        content = (
            f"<system-reminder>\nSkill '{name}' result:\n{result}\n</system-reminder>"
        )
        self._session.conversation.add_user(content)
        self._app.write_log(Text(f"[{name}] {result}", style="dim"))

    def clear_active_skills(self) -> None:
        agent = self._session.agent
        if agent is not None:
            agent.clear_active_skills()

    def track_skill_task(self, task: asyncio.Task[None]) -> None:
        self._session.track_skill_task(task)
