"""注册全部内置命令，每模块恰好一个命令。"""

from __future__ import annotations

from .handlers.clear import CLEAR_COMMAND
from .handlers.compact import COMPACT_COMMAND
from .handlers.do import DO_COMMAND
from .handlers.exit import EXIT_COMMAND
from .handlers.help import make_help_command
from .handlers.mcp import MCP_COMMAND
from .handlers.memory import MEMORY_COMMAND
from .handlers.permission import PERMISSION_COMMAND
from .handlers.plan import PLAN_COMMAND
from .handlers.resume import RESUME_COMMAND
from .handlers.review import REVIEW_COMMAND
from .handlers.sandbox import SANDBOX_COMMAND
from .handlers.session import SESSION_COMMAND
from .handlers.status import STATUS_COMMAND
from .registry import CommandRegistry


def register_builtins(registry: CommandRegistry) -> None:
    definitions = (
        CLEAR_COMMAND,
        COMPACT_COMMAND,
        DO_COMMAND,
        EXIT_COMMAND,
        MCP_COMMAND,
        MEMORY_COMMAND,
        PERMISSION_COMMAND,
        PLAN_COMMAND,
        RESUME_COMMAND,
        REVIEW_COMMAND,
        SANDBOX_COMMAND,
        SESSION_COMMAND,
        STATUS_COMMAND,
    )
    for command in definitions:
        registry.register(command)
    registry.register(make_help_command(registry))
