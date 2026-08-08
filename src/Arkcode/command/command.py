"""命令元数据与执行类型。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ui import UI


class Kind(Enum):
    LOCAL = "local"
    UI = "ui"
    PROMPT = "prompt"


Handler = Callable[["UI", str], Awaitable[None]]


@dataclass(slots=True)
class Command:
    name: str
    description: str
    kind: Kind
    handler: Handler
    aliases: list[str] = field(default_factory=list)
    hidden: bool = False
