"""Skill 管理命令与动态 Skill Slash 命令工厂。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Command, CommandContext, CommandKind
from ..registry import CommandRegistry

if TYPE_CHECKING:
    from ...skills import SkillExecutor, SkillLoader

USAGE = "Usage: /skill [list | info <name> | reload]"


def make_skill_management_command() -> Command:
    """返回不触发模型的 `/skill` 管理命令。"""

    async def handle_skill(context: CommandContext) -> None:
        parts = context.args.split()
        if not parts or parts == ["list"]:
            items = context.skills.list_skills()
            if not items:
                context.ui.println("No skills available.")
                return
            context.ui.println(
                "\n".join(
                    f"{name} - {description} ({source})"
                    for name, description, source in sorted(items)
                )
            )
            return
        if len(parts) == 2 and parts[0] == "info":
            info = context.skills.skill_info(parts[1].lower())
            if info is None:
                context.ui.error(f"Unknown skill: {parts[1]}")
            else:
                context.ui.println(info)
            return
        if parts == ["reload"]:
            context.skills.reload_skills()
            context.ui.println("Skills reloaded.")
            return
        context.ui.error(USAGE)

    return Command(
        "skill",
        "列出、查看或重新加载 Skills",
        CommandKind.LOCAL,
        handle_skill,
    )


def make_skill_command(name: str, description: str) -> Command:
    """构造单个 Skill 的动态 Slash 命令。"""

    async def handle_skill(context: CommandContext) -> None:
        await context.skills.invoke_skill(name, context.args)

    return Command(name, f"{description} [skill]", CommandKind.LOCAL, handle_skill)


def register_skill_management(
    registry: CommandRegistry,
    loader: SkillLoader,
) -> None:
    """注册不触发模型的 `/skill` 管理命令。"""

    _ = loader
    registry.register(make_skill_management_command())


def register_skill_commands(
    registry: CommandRegistry,
    loader: SkillLoader,
    executor: SkillExecutor,
) -> None:
    """把当前 Loader 中的每个 Skill 注册为同名 Slash 命令（可覆盖内置命令）。"""

    _ = executor
    for name, description in loader.get_catalog():
        registry.register(make_skill_command(name, description), replace=True)
