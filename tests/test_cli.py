from pathlib import Path
from typing import Any

import mcp.types as mtypes
import pytest

from Arkcode import cli
from Arkcode.mcp import Config, McpStatus
from Arkcode.mcp.tool import McpTool
from Arkcode.tool import Registry
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

    async def record_run_options(self: ArkCodeApp, **kwargs: object) -> None:
        run_options.append(kwargs)

    write_valid_env(tmp_path / ".env")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ArkCodeApp, "run_async", record_run_options)

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

    async def fail_to_start(self: ArkCodeApp, **kwargs: object) -> None:
        raise RuntimeError(f"SDK failed with key {secret}")

    monkeypatch.setattr(ArkCodeApp, "run_async", fail_to_start)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "ArkCode 启动失败" in stderr
    assert secret not in stderr


def test_main_registers_mcp_tools_and_closes_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    observed_names: list[str] = []
    observed_statuses: list[McpStatus] = []

    class Caller:
        async def call_tool(
            self, name: str, arguments: dict[str, Any] | None = None
        ) -> mtypes.CallToolResult:
            return mtypes.CallToolResult(content=[])

    remote_tool = McpTool(
        full_name="mcp__demo__echo",
        remote_name="echo",
        tool_description="echo",
        input_schema={"type": "object"},
        _read_only=True,
        caller=Caller(),
    )

    class FakeManager:
        def tools(self) -> list[McpTool]:
            return [remote_tool]

        def status(self) -> McpStatus:
            return McpStatus(2, 1, 1)

        async def close(self) -> None:
            events.append("closed")

    class FakeApp:
        async def run_async(self) -> None:
            events.append("ran")

    async def fake_new_manager(config: Config, version: str) -> FakeManager:
        events.append("connected")
        return FakeManager()

    def fake_new_app(
        providers: object,
        version: str,
        registry: Registry,
        engine: object,
        *,
        mcp_status: McpStatus,
    ) -> FakeApp:
        observed_names.extend(item.name for item in registry.definitions())
        observed_statuses.append(mcp_status)
        return FakeApp()

    write_valid_env(tmp_path / ".env")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.mcp_client, "load_config", lambda root: Config())
    monkeypatch.setattr(cli.mcp_client, "new_manager", fake_new_manager)
    monkeypatch.setattr(cli, "new_app", fake_new_app)

    cli.main()

    assert "mcp__demo__echo" in observed_names
    assert observed_statuses == [McpStatus(2, 1, 1)]
    assert events == ["connected", "ran", "closed"]
