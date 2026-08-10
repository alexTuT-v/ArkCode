"""/status 命令：显示当前运行状态。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_status(context: CommandContext) -> None:
    usage_in, usage_out = context.status.usage()
    rows = (
        ("Mode:", str(context.session.mode())),
        ("Tokens:", f"{usage_in} in / {usage_out} out"),
        ("Tools:", f"{context.status.tool_count()} enabled"),
        ("Memories:", f"{len(context.status.memory_files())} files"),
        ("Model:", context.status.model_name()),
        ("Directory:", context.status.cwd()),
    )
    width = max(len(key) for key, _ in rows)
    rendered = "\n".join(f"{key.ljust(width)} {value}" for key, value in rows)
    context.ui.println("ArkCode Status\n\n" + rendered)


STATUS_COMMAND = Command(
    "status",
    "显示当前运行状态",
    CommandKind.LOCAL,
    handle_status,
)
