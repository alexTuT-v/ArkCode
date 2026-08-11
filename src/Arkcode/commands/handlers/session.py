"""/session 命令：显示当前会话信息。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_session(context: CommandContext) -> None:
    parts = context.args.split(None, 1)
    sub = parts[0] if parts else ""
    if not sub:
        context.ui.println(
            "Session: "
            f"{context.status.session_id()}\n"
            f"Path: {context.status.session_path()}"
        )
        return
    if sub == "list":
        items = context.status.session_list()
        if not items:
            context.ui.println("没有已保存的会话")
            return
        lines = ["会话列表："]
        for item in items[:10]:
            lines.append(f"  {item.id}  {item.title}  [{item.size} bytes]")
        context.ui.println("\n".join(lines))
        return
    if sub == "resume":
        session_id = parts[1].strip() if len(parts) > 1 else ""
        if not session_id:
            context.ui.println("用法: /session resume <id>")
            return
        if not context.session.resume_by_id(session_id):
            context.ui.println(f"会话未找到: {session_id}")
        return
    if sub == "new":
        context.session.clear_session()
        context.ui.println("新会话已创建")
        return
    if sub == "delete":
        session_id = parts[1].strip() if len(parts) > 1 else ""
        if not session_id:
            context.ui.println("用法: /session delete <id>")
            return
        if session_id == context.status.session_id():
            context.ui.println("不能删除当前活跃的会话")
            return
        if context.session.delete_session(session_id):
            context.ui.println(f"会话已删除: {session_id}")
        else:
            context.ui.println(f"会话未找到: {session_id}")
        return
    context.ui.println("用法: /session [list | resume <id> | new | delete <id>]")


SESSION_COMMAND = Command(
    "session",
    "显示当前会话信息",
    CommandKind.LOCAL,
    handle_session,
    usage="/session [list | resume <id> | new | delete <id>]",
)
