"""注册全部内置命令。"""

from .builtin_local import (
    handle_memory,
    handle_permission,
    handle_session,
    handle_status,
    make_help_handler,
)
from .builtin_prompt import handle_do, handle_review
from .builtin_ui import (
    handle_clear,
    handle_compact,
    handle_exit,
    handle_plan,
    handle_resume,
)
from .command import Command, Kind
from .registry import Registry


def register_builtins(registry: Registry) -> None:
    definitions = (
        ("clear", "清空当前会话并开启新会话", Kind.UI, handle_clear),
        ("compact", "立即压缩当前上下文", Kind.UI, handle_compact),
        ("do", "执行已确认的计划", Kind.PROMPT, handle_do),
        ("exit", "退出 ArkCode", Kind.UI, handle_exit),
        ("help", "显示全部可用命令", Kind.LOCAL, make_help_handler(registry)),
        ("memory", "列出已加载的记忆文件", Kind.LOCAL, handle_memory),
        ("permission", "显示当前权限模式", Kind.LOCAL, handle_permission),
        ("plan", "切换到计划模式", Kind.UI, handle_plan),
        ("resume", "恢复历史会话", Kind.UI, handle_resume),
        ("review", "请求审查当前上下文", Kind.PROMPT, handle_review),
        ("session", "显示当前会话信息", Kind.LOCAL, handle_session),
        ("status", "显示当前运行状态", Kind.LOCAL, handle_status),
    )
    for name, description, kind, handler in definitions:
        registry.register(Command(name, description, kind, handler))
