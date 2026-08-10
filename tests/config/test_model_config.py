"""配置模型 pydantic 化结构测试。"""

import pytest

from Arkcode.config import Config, ProviderConfig


def test_provider_config_is_frozen_and_repr_hides_key() -> None:
    config = ProviderConfig(
        name="Claude",
        protocol="anthropic",
        api_key="secret",
        model="claude-test",
    )

    assert config.base_url is None
    assert config.thinking is False
    assert config.context_window == 0
    assert "secret" not in repr(config)
    with pytest.raises(Exception):
        config.model = "other"  # type: ignore[misc]


def test_config_ignores_unknown_fields() -> None:
    config = Config.model_validate(
        {
            "providers": [],
            "unexpected": 1,
        }
    )

    assert config.providers == []
