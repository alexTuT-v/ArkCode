from pathlib import Path

import pytest

from Arkcode import cli
from Arkcode.tui.app import ArkCodeApp


def write_valid_env(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "ARKCODE_PROVIDERS=Claude",
                "ARKCODE_CLAUDE_PROTOCOL=anthropic",
                "ARKCODE_CLAUDE_API_KEY=secret",
                "ARKCODE_CLAUDE_MODEL=claude-test",
            ]
        ),
        encoding="utf-8",
    )


def test_main_starts_with_root_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_options: list[dict[str, object]] = []

    def record_run_options(self: ArkCodeApp, **kwargs: object) -> None:
        run_options.append(kwargs)

    write_valid_env(tmp_path / ".env")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ArkCodeApp, "run", record_run_options)

    cli.main()

    assert run_options == [{}]


def test_main_does_not_fall_back_to_legacy_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy = tmp_path / ".Arkcode" / "config.yaml"
    legacy.parent.mkdir()
    legacy.write_text("providers: []\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert "配置文件不存在: .env" in capsys.readouterr().err


def test_main_redacts_secrets_from_startup_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "do-not-print-this-secret"
    write_valid_env(tmp_path / ".env")
    (tmp_path / ".env").write_text(
        (tmp_path / ".env").read_text(encoding="utf-8").replace("secret", secret),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    def fail_to_start(self: ArkCodeApp, **kwargs: object) -> None:
        raise RuntimeError(f"SDK failed with key {secret}")

    monkeypatch.setattr(ArkCodeApp, "run", fail_to_start)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "ArkCode 启动失败" in stderr
    assert secret not in stderr
