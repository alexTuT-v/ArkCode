"""/sandbox 命令：OS 级沙箱三态切换。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_sandbox(context: CommandContext) -> None:
    parts = context.args.split(None, 1)
    sub = parts[0] if parts else ""
    if not sub:
        status = context.sandbox.status()
        context.ui.println(
            "\n".join(
                (
                    "沙箱状态",
                    f"  OS 沙箱: {'已启用' if status.enabled else '未启用'}",
                    f"  自动放行: {'是' if status.auto_allow else '否'}",
                    f"  后端: {status.backend or '无'}",
                    f"  后端可用: {'是' if status.available else '否'}",
                )
            )
        )
        return
    if sub in ("1", "on-auto"):
        error = context.sandbox.enable(True)
        context.ui.println(error if error else "沙箱已启用（自动放行）")
        return
    if sub in ("2", "on"):
        error = context.sandbox.enable(False)
        context.ui.println(error if error else "沙箱已启用（常规权限）")
        return
    if sub in ("3", "off"):
        context.sandbox.disable()
        context.ui.println("沙箱已关闭")
        return
    context.ui.println("用法: /sandbox [1|on-auto | 2|on | 3|off]")


SANDBOX_COMMAND = Command(
    "sandbox",
    "沙箱管理",
    CommandKind.LOCAL,
    handle_sandbox,
    usage="/sandbox [1|on-auto | 2|on | 3|off]",
)
