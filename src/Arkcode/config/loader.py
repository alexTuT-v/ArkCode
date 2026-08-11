"""环境变量配置加载与校验。"""

import os
import re
from pathlib import Path
from typing import cast

from dotenv import load_dotenv

from .models import (
    Config,
    ConfigError,
    Features,
    ProtocolName,
    ProviderConfig,
)

_PROTOCOLS = {"anthropic", "openai"}
_PROVIDER_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def _required(variable: str) -> str:
    value = os.environ.get(variable, "").strip()
    if not value:
        raise ConfigError(f"{variable} 不能为空")
    return value


def _provider_names() -> list[str]:
    raw = os.environ.get("ARKCODE_PROVIDERS", "")
    names = [name.strip() for name in raw.split(",")]
    if not raw.strip() or any(not name for name in names):
        raise ConfigError("ARKCODE_PROVIDERS 不能为空")

    normalized: set[str] = set()
    for index, name in enumerate(names, start=1):
        if _PROVIDER_NAME.fullmatch(name) is None:
            raise ConfigError(
                f"ARKCODE_PROVIDERS 第 {index} 项名称仅允许字母、数字和下划线"
            )
        key = name.upper()
        if key in normalized:
            raise ConfigError("ARKCODE_PROVIDERS 包含重复的 provider 名称")
        normalized.add(key)
    return names


def _from_environment() -> Config:
    names = _provider_names()
    providers: list[ProviderConfig] = []
    for name in names:
        prefix = f"ARKCODE_{name.upper()}_"
        protocol_variable = f"{prefix}PROTOCOL"
        protocol = _required(protocol_variable)
        if protocol not in _PROTOCOLS:
            raise ConfigError(f"{protocol_variable} 必须是 anthropic 或 openai")

        thinking_variable = f"{prefix}THINKING"
        thinking_text = os.environ.get(thinking_variable, "false").strip()
        if thinking_text not in {"true", "false"}:
            raise ConfigError(f"{thinking_variable} 必须是 true 或 false")

        context_window_variable = f"{prefix}CONTEXT_WINDOW"
        context_window_text = os.environ.get(context_window_variable, "0").strip()
        try:
            context_window = int(context_window_text or "0")
        except ValueError as exc:
            raise ConfigError(f"{context_window_variable} 必须是非负整数") from exc
        if context_window < 0:
            raise ConfigError(f"{context_window_variable} 必须是非负整数")

        providers.append(
            ProviderConfig(
                name=name,
                protocol=cast(ProtocolName, protocol),
                api_key=_required(f"{prefix}API_KEY"),
                model=_required(f"{prefix}MODEL"),
                base_url=os.environ.get(f"{prefix}BASE_URL", "").strip() or None,
                thinking=thinking_text == "true",
                context_window=context_window,
            )
        )

    def _truthy(value: str | None, default: bool = False) -> bool:
        if value is None or not value.strip():
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    background = _truthy(
        os.environ.get("ARKCODE_ENABLE_SUBAGENT_BACKGROUND"),
        True,
    )
    coordinator_feature = _truthy(
        os.environ.get("ARKCODE_FEATURE_COORDINATOR_MODE"),
        False,
    )
    return Config(
        providers=providers,
        features=Features(coordinator_mode=coordinator_feature),
        enable_subagent_background=background,
    )


def effective_context_window(provider: ProviderConfig) -> int:
    """返回显式窗口配置，缺省时使用协议的保守默认值。"""

    if provider.context_window > 0:
        return provider.context_window
    if provider.protocol == "openai":
        return 128000
    return 200000


def load(path: str) -> Config:
    """从 ``path`` 加载并校验配置。"""

    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"配置文件不存在: {path}")
    load_dotenv(dotenv_path=config_path, override=True)
    return _from_environment()
