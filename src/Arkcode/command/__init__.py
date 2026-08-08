"""Slash Command 领域模型、注册与内置命令。"""

from .builtins import register_builtins
from .command import Command, Handler, Kind
from .dispatch import parse
from .registry import Registry
from .skills import register_skill_commands, register_skill_management
from .ui import UI, NopUI

__all__ = [
    "Command",
    "Handler",
    "Kind",
    "NopUI",
    "Registry",
    "UI",
    "parse",
    "register_builtins",
    "register_skill_commands",
    "register_skill_management",
]
