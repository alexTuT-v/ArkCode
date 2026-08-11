"""/worktree 命令：手动管理隔离 Worktree。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_worktree(context: CommandContext) -> None:
    args = context.args.strip().split()
    if not args:
        context.ui.error(
            "用法: /worktree create <slug> | list | enter <slug> | "
            "exit [--remove] [--discard] | remove <slug> [--discard]"
        )
        return
    action = args[0]
    rest = args[1:]
    if action == "create" and len(rest) == 1:
        context.ui.println(await context.worktree.create_worktree(rest[0]))
    elif action == "list":
        for name, path, branch, active in context.worktree.list_worktrees():
            marker = "  [active]" if active else ""
            context.ui.println(f"{name}  {path}  {branch}{marker}")
    elif action == "enter" and len(rest) == 1:
        context.ui.println(await context.worktree.enter_worktree(rest[0]))
    elif action == "exit":
        remove = "--remove" in rest
        discard = "--discard" in rest
        context.ui.println(
            await context.worktree.exit_worktree(
                remove=remove,
                discard=discard,
            )
        )
    elif action == "remove" and len(rest) >= 1:
        discard = "--discard" in rest
        slug = rest[0]
        context.ui.println(
            await context.worktree.remove_worktree(slug, discard=discard)
        )
    else:
        context.ui.error("参数不正确，请查看 /help worktree")


WORKTREE_COMMAND = Command(
    "worktree",
    "管理隔离 Worktree（create/list/enter/exit/remove）",
    CommandKind.LOCAL,
    handle_worktree,
)
