import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from Arkcode.config import ConfigError, ProviderConfig, effective_context_window, load


@pytest.fixture(autouse=True)
def restore_arkcode_environment() -> Iterator[None]:
    original = {
        key: value for key, value in os.environ.items() if key.startswith("ARKCODE_")
    }
    for key in original:
        del os.environ[key]
    yield
    for key in tuple(os.environ):
        if key.startswith("ARKCODE_"):
            del os.environ[key]
    os.environ.update(original)


def write_env(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_providers_in_declared_order(tmp_path: Path) -> None:
    path = write_env(
        tmp_path / ".env",
        """
ARKCODE_PROVIDERS=Claude,GPT
ARKCODE_CLAUDE_PROTOCOL=anthropic
ARKCODE_CLAUDE_API_KEY=anthropic-secret
ARKCODE_CLAUDE_MODEL=claude-test
ARKCODE_CLAUDE_BASE_URL=https://anthropic.example/v1
ARKCODE_CLAUDE_THINKING=true
ARKCODE_GPT_PROTOCOL=openai
ARKCODE_GPT_API_KEY=openai-secret
ARKCODE_GPT_MODEL=gpt-test
""",
    )

    config = load(str(path))

    assert len(config.providers) == 2
    assert config.providers[0].name == "Claude"
    assert config.providers[0].base_url == "https://anthropic.example/v1"
    assert config.providers[0].thinking is True
    assert config.providers[1].base_url is None
    assert config.providers[1].thinking is False


def test_trims_provider_names_and_uses_uppercase_prefix(tmp_path: Path) -> None:
    path = write_env(
        tmp_path / ".env",
        """
ARKCODE_PROVIDERS= deepSeek
ARKCODE_DEEPSEEK_PROTOCOL=anthropic
ARKCODE_DEEPSEEK_API_KEY=secret
ARKCODE_DEEPSEEK_MODEL=deepseek-test
""",
    )

    config = load(str(path))

    assert config.providers[0].name == "deepSeek"


def test_dotenv_values_override_system_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARKCODE_PROVIDERS", "system")
    monkeypatch.setenv("ARKCODE_SYSTEM_PROTOCOL", "openai")
    monkeypatch.setenv("ARKCODE_SYSTEM_API_KEY", "system-secret")
    monkeypatch.setenv("ARKCODE_SYSTEM_MODEL", "system-model")
    path = write_env(
        tmp_path / ".env",
        """
ARKCODE_PROVIDERS=file
ARKCODE_FILE_PROTOCOL=anthropic
ARKCODE_FILE_API_KEY=file-secret
ARKCODE_FILE_MODEL=file-model
""",
    )

    config = load(str(path))

    assert config.providers[0].name == "file"
    assert config.providers[0].model == "file-model"


def test_reports_missing_file_without_traceback(tmp_path: Path) -> None:
    missing = tmp_path / ".env"

    with pytest.raises(ConfigError, match=f"配置文件不存在: {missing}"):
        load(str(missing))


@pytest.mark.parametrize("body", ["", "ARKCODE_PROVIDERS=  ,  \n"])
def test_rejects_missing_or_empty_provider_list(tmp_path: Path, body: str) -> None:
    path = write_env(tmp_path / ".env", body)

    with pytest.raises(ConfigError, match="ARKCODE_PROVIDERS 不能为空"):
        load(str(path))


@pytest.mark.parametrize("name", ["bad-name", "bad.name", "名字"])
def test_rejects_invalid_provider_name(tmp_path: Path, name: str) -> None:
    path = write_env(tmp_path / ".env", f"ARKCODE_PROVIDERS={name}\n")

    with pytest.raises(ConfigError, match="仅允许字母、数字和下划线"):
        load(str(path))


def test_invalid_provider_name_error_does_not_reveal_value(tmp_path: Path) -> None:
    secret = "do-not-print-this-secret!"
    path = write_env(tmp_path / ".env", f"ARKCODE_PROVIDERS={secret}\n")

    with pytest.raises(ConfigError) as exc_info:
        load(str(path))

    assert secret not in str(exc_info.value)


def test_rejects_duplicate_provider_names_case_insensitively(tmp_path: Path) -> None:
    path = write_env(tmp_path / ".env", "ARKCODE_PROVIDERS=Claude,claude\n")

    with pytest.raises(ConfigError, match="重复的 provider 名称") as exc_info:
        load(str(path))

    assert "claude" not in str(exc_info.value)


@pytest.mark.parametrize("field", ["PROTOCOL", "API_KEY", "MODEL"])
def test_rejects_missing_required_provider_field(tmp_path: Path, field: str) -> None:
    values = {
        "PROTOCOL": "anthropic",
        "API_KEY": "secret",
        "MODEL": "claude-test",
    }
    del values[field]
    variables = "\n".join(
        f"ARKCODE_CLAUDE_{key}={value}" for key, value in values.items()
    )
    path = write_env(
        tmp_path / ".env",
        f"ARKCODE_PROVIDERS=Claude\n{variables}\n",
    )

    with pytest.raises(ConfigError, match=f"ARKCODE_CLAUDE_{field} 不能为空"):
        load(str(path))


def test_rejects_unknown_protocol(tmp_path: Path) -> None:
    path = write_env(
        tmp_path / ".env",
        """
ARKCODE_PROVIDERS=Other
ARKCODE_OTHER_PROTOCOL=unknown
ARKCODE_OTHER_API_KEY=secret
ARKCODE_OTHER_MODEL=model
""",
    )

    with pytest.raises(
        ConfigError,
        match="ARKCODE_OTHER_PROTOCOL 必须是 anthropic 或 openai",
    ):
        load(str(path))


def test_empty_base_url_and_missing_thinking_use_defaults(tmp_path: Path) -> None:
    path = write_env(
        tmp_path / ".env",
        """
ARKCODE_PROVIDERS=Claude
ARKCODE_CLAUDE_PROTOCOL=anthropic
ARKCODE_CLAUDE_API_KEY=secret
ARKCODE_CLAUDE_MODEL=claude-test
ARKCODE_CLAUDE_BASE_URL=
""",
    )

    provider = load(str(path)).providers[0]

    assert provider.base_url is None
    assert provider.thinking is False


@pytest.mark.parametrize("value", ["yes", "1", "TRUE-ish"])
def test_rejects_invalid_thinking_value(tmp_path: Path, value: str) -> None:
    path = write_env(
        tmp_path / ".env",
        f"""
ARKCODE_PROVIDERS=Claude
ARKCODE_CLAUDE_PROTOCOL=anthropic
ARKCODE_CLAUDE_API_KEY=secret
ARKCODE_CLAUDE_MODEL=claude-test
ARKCODE_CLAUDE_THINKING={value}
""",
    )

    with pytest.raises(
        ConfigError, match="ARKCODE_CLAUDE_THINKING 必须是 true 或 false"
    ):
        load(str(path))


def test_provider_repr_does_not_reveal_api_key(tmp_path: Path) -> None:
    path = write_env(
        tmp_path / ".env",
        """
ARKCODE_PROVIDERS=Claude
ARKCODE_CLAUDE_PROTOCOL=anthropic
ARKCODE_CLAUDE_API_KEY=do-not-print-this-secret
ARKCODE_CLAUDE_MODEL=claude-test
""",
    )

    provider = load(str(path)).providers[0]

    assert "do-not-print-this-secret" not in repr(provider)


def test_context_window_loads_from_environment(tmp_path: Path) -> None:
    path = write_env(
        tmp_path / ".env",
        """
ARKCODE_PROVIDERS=Claude
ARKCODE_CLAUDE_PROTOCOL=anthropic
ARKCODE_CLAUDE_API_KEY=secret
ARKCODE_CLAUDE_MODEL=claude-test
ARKCODE_CLAUDE_CONTEXT_WINDOW=80000
""",
    )

    assert load(str(path)).providers[0].context_window == 80000


def test_effective_context_window_uses_override_or_protocol_default() -> None:
    anthropic = ProviderConfig(
        name="a", protocol="anthropic", api_key="secret", model="model"
    )
    openai = ProviderConfig(
        name="o", protocol="openai", api_key="secret", model="model"
    )
    overridden = ProviderConfig(
        name="custom",
        protocol="anthropic",
        api_key="secret",
        model="model",
        context_window=80000,
    )

    assert effective_context_window(anthropic) == 200000
    assert effective_context_window(openai) == 128000
    assert effective_context_window(overridden) == 80000
