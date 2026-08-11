"""TUI 会话阶段状态、模式切换与展示状态代理。"""

from __future__ import annotations

import asyncio
from enum import Enum

from ..agents import Agent, SessionRuntime
from ..application import SessionService
from ..conversations import Conversation
from ..llm import Provider
from ..permissions import Mode
from ..sessions import SessionJournal
from ..skills import SkillExecutor
from ..tools import Registry
from .streaming import StreamingController
from .streaming.state import ToolDisplay


class AppStateMixin:
    """把会话服务与流式状态暴露为 App 上的只读展示代理。"""

    session: SessionService
    streaming: StreamingController
    _tool_registry: Registry

    @property
    def conv(self) -> Conversation:
        return self.session.conversation

    @property
    def journal(self) -> SessionJournal:
        return self.session.journal

    @property
    def runtime(self) -> SessionRuntime:
        return self.session.runtime

    @property
    def tool_registry(self) -> Registry:
        return self._tool_registry

    @property
    def mode(self) -> Mode:
        return self.session.mode

    @mode.setter
    def mode(self, value: Mode) -> None:
        self.session.mode = value

    @property
    def provider(self) -> Provider | None:
        return self.session.provider

    @property
    def agent(self) -> Agent | None:
        return self.session.agent

    @agent.setter
    def agent(self, value: Agent | None) -> None:
        self.session.agent = value

    @property
    def skill_executor(self) -> SkillExecutor | None:
        return self.session.skill_executor

    @property
    def _fork_tasks(self) -> set[asyncio.Task[None]]:
        return self.session.skill_tasks

    @property
    def cur_reply(self) -> str:
        return self.streaming.state.reply

    @property
    def cur_thinking(self) -> str:
        return self.streaming.state.thinking

    @property
    def cur_tools(self) -> list[ToolDisplay]:
        return self.streaming.state.tools

    @property
    def iter(self) -> int:
        return self.streaming.state.iteration


class SessionState(Enum):
    """当前会话所处的交互阶段。"""

    SELECTING = "selecting"
    IDLE = "idle"
    STREAMING = "streaming"
    APPROVING = "approving"
    RESUMING = "resuming"


def next_mode(mode: Mode) -> Mode:
    """按 UI 展示顺序循环到下一档权限模式。"""

    cycle = (
        Mode.DEFAULT,
        Mode.ACCEPT_EDITS,
        Mode.PLAN,
        Mode.BYPASS,
    )
    try:
        index = cycle.index(mode)
    except ValueError:
        return Mode.DEFAULT
    return cycle[(index + 1) % len(cycle)]
