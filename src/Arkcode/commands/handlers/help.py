"""/help 命令：显示全部可用命令（依赖活动注册表，使用工厂构造）。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind
from ..registry import CommandRegistry


def make_help_command(registry: CommandRegistry) -> Command:
    async def handle_help(context: CommandContext) -> None:
        name = context.args.strip()
        if not name:
            commands = registry.visible()
            width = max((len(command.name) for command in commands), default=0)
            context.ui.println(
                "\n".join(
                    f"/{command.name.ljust(width)}  {command.description}"
                    for command in commands
                )
            )
            return
        command = registry.lookup(name)
        if command is None:
            context.ui.println(f"未知命令：{name}，输入 /help 查看可用命令")
            return
        lines = [f"/{command.name}"]
        if command.aliases:
            aliases = ", ".join(f"/{alias}" for alias in command.aliases)
            lines[0] += f"  (别名: {aliases})"
        lines.append(f"  {command.description}")
        if command.usage:
            lines.append(f"  用法: {command.usage}")
        if command.arg_prompt:
            lines.append(f"  参数: {command.arg_prompt}")
        context.ui.println("\n".join(lines))

    return Command(
        "help",
        "显示全部可用命令",
        CommandKind.LOCAL,
        handle_help,
        usage="/help [命令名]",
    )
