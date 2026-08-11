"""不可变的应用配置模型。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProtocolName = Literal["anthropic", "openai"]


class ConfigError(Exception):
    """配置不可用时抛出的可读错误。"""


class ProviderConfig(BaseModel):
    """单个模型服务配置。"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    protocol: ProtocolName
    api_key: str = Field(repr=False)
    model: str
    base_url: str | None = None
    thinking: bool = False
    context_window: int = 0


class Features(BaseModel):
    """功能开关集合。"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    coordinator_mode: bool = False


class Config(BaseModel):
    """应用配置。"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    providers: list[ProviderConfig]
    features: Features = Field(default_factory=Features)
    enable_subagent_background: bool = True
