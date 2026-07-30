"""与供应商无关的消息、流事件和 Provider 协议。"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

from ..config import ProviderConfig


@dataclass(frozen=True)
class Message:
    """单条对话消息。"""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class StreamEvent:
    """统一的模型流事件。"""

    text: str = ""
    done: bool = False
    err: Exception | None = None


class Provider(Protocol):
    """TUI 使用的协议无关模型接口。"""

    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def stream(self, msgs: list[Message]) -> AsyncIterator[StreamEvent]: ...


def new_provider(cfg: ProviderConfig) -> Provider:
    """根据配置创建相应协议适配器。"""

    if cfg.protocol == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg)
    if cfg.protocol == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(cfg)
    raise ValueError(f"不支持的 provider protocol: {cfg.protocol}")
