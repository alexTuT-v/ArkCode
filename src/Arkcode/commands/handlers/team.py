"""/team 命令：团队管理与人工介入。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_team(context: CommandContext) -> None:
    args = context.args.strip().split()
    if not args:
        context.ui.error(
            "用法: /team list | info <name> | delete <name> [--force] | kill <member>"
        )
        return
    action = args[0]
    rest = args[1:]
    if action == "list":
        for name, backend, total, active in context.team.list_teams():
            context.ui.println(
                f"{name}  {backend}  {total} 成员  [{active}/{total}] 活跃"
            )
    elif action == "info" and len(rest) == 1:
        context.ui.println(await context.team.team_info(rest[0]))
    elif action == "delete" and len(rest) >= 1:
        force = "--force" in rest
        context.ui.println(
            await context.team.delete_team(rest[0], force)
        )
    elif action == "kill" and len(rest) == 1:
        context.ui.println(await context.team.kill_member(rest[0]))
    else:
        context.ui.error("参数不正确，请查看 /help team")


TEAM_COMMAND = Command(
    "team",
    "管理 Agent Team（list/info/delete/kill）",
    CommandKind.LOCAL,
    handle_team,
)
