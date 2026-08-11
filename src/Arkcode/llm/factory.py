"""Provider 构造工厂。"""

from ..config import ProviderConfig
from .providers.anthropic import AnthropicProvider
from .providers.openai import OpenAIProvider
from .types import Provider


def new_provider(cfg: ProviderConfig) -> Provider:
    """根据配置创建相应协议适配器。"""

    if cfg.protocol == "anthropic":
        return AnthropicProvider(cfg)
    if cfg.protocol == "openai":
        return OpenAIProvider(cfg)
    raise ValueError(f"不支持的 provider protocol: {cfg.protocol}")
