"""Skill 管理命令与动态 Slash 命令注册。"""

import asyncio

from ..skills import SkillExecutor, SkillLoader
from .command import Command, Kind
from .registry import Registry
from .ui import UI

USAGE = "Usage: /skill [list | info <name> | reload]"


def register_skill_management(registry: Registry, loader: SkillLoader) -> None:
    """注册不触发模型的 `/skill` 管理命令。"""

    _ = loader

    async def handle_skill(ui: UI, args: str) -> None:
        parts = args.split()
        if not parts or parts == ["list"]:
            items = ui.skill_list()
            if not items:
                ui.println("No skills available.")
                return
            ui.println(
                "\n".join(
                    f"{name} - {description} ({source})"
                    for name, description, source in sorted(items)
                )
            )
            return
        if len(parts) == 2 and parts[0] == "info":
            info = ui.skill_info(parts[1].lower())
            if info is None:
                ui.error(f"Unknown skill: {parts[1]}")
            else:
                ui.println(info)
            return
        if parts == ["reload"]:
            ui.reload_skills()
            ui.println("Skills reloaded.")
            return
        ui.error(USAGE)

    registry.register(
        Command(
            "skill",
            "列出、查看或重新加载 Skills",
            Kind.LOCAL,
            handle_skill,
        )
    )


def register_skill_commands(
    registry: Registry,
    loader: SkillLoader,
    executor: SkillExecutor,
) -> None:
    """把当前 Loader 中的每个 Skill 注册为同名 Slash 命令。"""

    for name, description in loader.get_catalog():

        async def handle_skill(
            ui: UI,
            args: str,
            *,
            skill_name: str = name,
        ) -> None:
            current = loader.get(skill_name)
            if current is None:
                ui.error(f"Unknown skill: {skill_name}. Try /skill reload.")
                return
            if current.mode == "inline":
                executor.execute_inline(current, args)
                trigger = f"/{skill_name}" + (f" {args}" if args else "")
                ui.inject_and_send(f"/{skill_name}", trigger)
                return

            async def run_fork() -> None:
                try:
                    result = await executor.execute_fork(current, args)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    result = f"[skill {skill_name} failed: {error}]"
                ui.append_system_message(skill_name, result)

            task = asyncio.create_task(run_fork())
            ui.track_skill_task(task)

        registry.register(
            Command(
                name,
                f"{description} [skill]",
                Kind.LOCAL,
                handle_skill,
            ),
            replace=True,
        )
