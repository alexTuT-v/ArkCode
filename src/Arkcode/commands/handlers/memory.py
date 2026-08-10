"""/memory 命令：列出已加载的记忆文件。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_memory(context: CommandContext) -> None:
    parts = context.args.split(None, 1)
    sub = parts[0] if parts else ""
    if sub in ("", "list"):
        files = context.status.memory_files()
        context.ui.println("\n".join(files) if files else "无已加载的记忆文件")
        return
    if sub == "clear":
        context.session.clear_memory()
        context.ui.println("所有记忆已清空")
        return
    if sub == "edit":
        project_dir, user_dir = context.status.memory_dirs()
        context.ui.println(f"项目级记忆目录: {project_dir}\n用户级记忆目录: {user_dir}")
        return
    context.ui.println("用法: /memory [list | clear | edit]")


MEMORY_COMMAND = Command(
    "memory",
    "列出已加载的记忆文件",
    CommandKind.LOCAL,
    handle_memory,
    usage="/memory [list | clear | edit]",
)
