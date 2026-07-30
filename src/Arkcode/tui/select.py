"""Provider 选择界面的展示数据。"""

from ..config import ProviderConfig


def provider_options(providers: list[ProviderConfig]) -> list[str]:
    """返回方向键选择列表使用的可读标签。"""

    return [f"{provider.name} ({provider.model})" for provider in providers]
