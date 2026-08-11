"""父会话上下文：子 Agent 启动所需的父级绑定。"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..conversations import Conversation
from ..llm import Provider
from .identity import AgentIdentity

if TYPE_CHECKING:
    from ..config import Config, ProviderConfig
    from ..tools import Registry


@dataclass(slots=True)
class ParentContext:
    """子 Agent 启动时可见的父会话快照。"""

    workspace: Path
    conversation: Conversation
    identity: AgentIdentity
    registry: Registry
    provider: Provider | None = None
    provider_config: ProviderConfig | None = None
    config: Config | None = None


_parent_context: contextvars.ContextVar[ParentContext | None] = contextvars.ContextVar(
    "arkcode_parent_context",
    default=None,
)


def current_parent() -> ParentContext | None:
    return _parent_context.get()


@contextmanager
def parent_scope(context: ParentContext) -> Iterator[None]:
    token = _parent_context.set(context)
    try:
        yield
    finally:
        try:
            _parent_context.reset(token)
        except ValueError:
            pass
