"""Provider 构造工厂。"""

from ..config import ProviderConfig
from .types import Provider


def new_provider(cfg: ProviderConfig) -> Provider:
    """根据配置创建相应协议适配器。"""

    if cfg.protocol == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg)
    if cfg.protocol == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(cfg)
    raise ValueError(f"不支持的 provider protocol: {cfg.protocol}")
