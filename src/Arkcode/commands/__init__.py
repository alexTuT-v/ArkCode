"""Slash 命令领域模型、注册、分发与内置命令。"""

from .builtins import register_builtins
from .dispatcher import dispatch
from .handlers.skill import (
    register_skill_commands,
    register_skill_management,
)
from .loader import register_custom_commands
from .models import (
    Command,
    CommandContext,
    CommandKind,
    Handler,
    McpServerInfo,
    SandboxStatus,
)
from .parser import parse
from .ports import (
    CommandUI,
    SandboxCommands,
    SessionCommands,
    SkillCommands,
    StatusQueries,
)
from .registry import CommandRegistry

__all__ = [
    "Command",
    "CommandContext",
    "CommandKind",
    "CommandRegistry",
    "CommandUI",
    "Handler",
    "SandboxCommands",
    "SandboxStatus",
    "McpServerInfo",
    "SessionCommands",
    "SkillCommands",
    "StatusQueries",
    "dispatch",
    "parse",
    "register_builtins",
    "register_custom_commands",
    "register_skill_commands",
    "register_skill_management",
]
