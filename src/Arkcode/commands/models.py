"""Slash 命令元数据、执行上下文与命令类型。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum

from .ports import (
    CommandUI,
    SandboxCommands,
    SessionCommands,
    SkillCommands,
    StatusQueries,
    TeamCommands,
    WorktreeCommands,
)


class CommandKind(Enum):
    LOCAL = "local"
    UI = "ui"
    PROMPT = "prompt"


@dataclass(frozen=True, slots=True)
class CommandContext:
    """单个命令执行时可访问的强类型端口集合。"""

    args: str
    session: SessionCommands
    skills: SkillCommands
    status: StatusQueries
    ui: CommandUI
    sandbox: SandboxCommands
    worktree: WorktreeCommands = field(default_factory=lambda: _NullWorktreeCommands())
    team: TeamCommands = field(default_factory=lambda: _NullTeamCommands())


@dataclass(frozen=True, slots=True)
class McpServerInfo:
    """命令层可见的单个 MCP server 状态。"""

    name: str
    tool_count: int
    connected: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SandboxStatus:
    enabled: bool
    auto_allow: bool
    backend: str
    available: bool


Handler = Callable[[CommandContext], Awaitable[None]]


class _NullWorktreeCommands:
    """未装配 Worktree 时用的默认实现。"""

    async def create_worktree(self, slug: str) -> str:
        return "错误: Worktree 功能未启用"

    def list_worktrees(self) -> list[tuple[str, str, str, bool]]:
        return []

    async def enter_worktree(self, slug: str) -> str:
        return "错误: Worktree 功能未启用"

    async def exit_worktree(self, *, remove: bool, discard: bool) -> str:
        return "错误: Worktree 功能未启用"

    async def remove_worktree(self, slug: str, *, discard: bool) -> str:
        return "错误: Worktree 功能未启用"


class _NullTeamCommands:
    def list_teams(self) -> list[tuple[str, str, int, int]]:
        return []

    async def team_info(self, name: str) -> str:
        return "错误: Team 功能未启用"

    async def delete_team(self, name: str, force: bool) -> str:
        return "错误: Team 功能未启用"

    async def kill_member(self, member: str) -> str:
        return "错误: Team 功能未启用"


@dataclass(slots=True)
class Command:
    name: str
    description: str
    kind: CommandKind
    handler: Handler
    aliases: list[str] = field(default_factory=list)
    usage: str = ""
    arg_prompt: str = ""
    hidden: bool = False
