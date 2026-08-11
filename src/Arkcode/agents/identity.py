"""Agent 身份与调用来源的 ContextVar 上下文。

AgentIdentity 同时通过 Agent 构造参数与 ContextVar 提供：Agent 本身用于
事件和 trace；Tool 调用使用 ContextVar 判断调用来源、权限作用域与 Team
上下文。Fork 嵌套拦截不得依赖模型可伪造的普通参数。
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

AgentSource = Literal["main", "defined", "fork", "skill", "teammate"]


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """一次 Agent 运行的稳定身份。"""

    agent_id: str
    parent_id: str
    trace_id: str
    agent_type: str
    name: str
    source: AgentSource
    team_name: str = ""

    @classmethod
    def main(cls, workspace: str = "") -> AgentIdentity:
        """构造主 Agent（Lead）的默认身份。"""

        return cls(
            agent_id="lead",
            parent_id="",
            trace_id=uuid.uuid4().hex[:12],
            agent_type="main",
            name="lead",
            source="main",
        )


_current_identity: contextvars.ContextVar[AgentIdentity] = contextvars.ContextVar(
    "arkcode_current_identity",
)


def current_identity() -> AgentIdentity:
    """读取当前调用身份；无显式上下文时回退为主 Agent 身份。"""

    try:
        return _current_identity.get()
    except LookupError:
        return AgentIdentity.main()


@contextmanager
def identity_scope(identity: AgentIdentity) -> Iterator[None]:
    """在作用域内设置调用身份，退出后自动恢复。"""

    token = _current_identity.set(identity)
    try:
        yield
    finally:
        try:
            _current_identity.reset(token)
        except ValueError:
            # 生成器被跨上下文关闭时容忍丢失的 token。
            pass
