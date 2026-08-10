"""权限裁决的基础类型与模式解析。"""

from enum import IntEnum


class Mode(IntEnum):
    DEFAULT = 0
    ACCEPT_EDITS = 1
    PLAN = 2
    BYPASS = 3
    NORMAL = DEFAULT

    def __str__(self) -> str:
        return ("default", "acceptEdits", "plan", "bypassPermissions")[self]


class Decision(IntEnum):
    ALLOW = 0
    DENY = 1
    ASK = 2


class Category(IntEnum):
    READ = 0
    WRITE = 1
    EXEC = 2


class Outcome(IntEnum):
    DENY_ONCE = 0
    ALLOW_ONCE = 1
    ALLOW_FOREVER = 2


def parse_mode(value: str) -> tuple[Mode, bool]:
    for mode in Mode:
        if value.lower() == str(mode).lower():
            return mode, True
    return Mode.DEFAULT, False


class ApprovalError(RuntimeError):
    """权限审批流程无法完成。"""
