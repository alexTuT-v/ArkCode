from pathlib import Path

import pytest

from Arkcode.mcp import Config, ServerConfig, load_config


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_missing_files_produce_empty_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    assert load_config(str(tmp_path / "project")) == Config()


def test_project_server_completely_overrides_user_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    _write(
        home / ".Arkcode" / "config.yaml",
        """mcp_servers:
  shared:
    type: stdio
    command: from-user
    args: [user-arg]
  user-only:
    type: http
    url: https://user.example/mcp
""",
    )
    _write(
        project / ".Arkcode" / "settings.yaml",
        """default_mode: default
permissions:
  allow: [Read]
mcp_servers:
  shared:
    type: http
    url: https://project.example/mcp
""",
    )

    config = load_config(str(project))

    assert set(config.servers) == {"shared", "user-only"}
    assert config.servers["shared"].type == "http"
    assert config.servers["shared"].url == "https://project.example/mcp"
    assert config.servers["shared"].command == ""


def test_invalid_yaml_skips_only_that_layer_and_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    _write(home / ".Arkcode" / "config.yaml", "mcp_servers: [")
    _write(
        project / ".Arkcode" / "settings.yaml",
        "mcp_servers:\n  good:\n    type: stdio\n    command: python\n",
    )

    config = load_config(str(project))

    assert set(config.servers) == {"good"}
    assert "[mcp] warn: load" in capsys.readouterr().err


def test_env_and_headers_expand_but_command_and_args_do_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("DEFINED_TOKEN", "expanded")
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    _write(
        project / ".Arkcode" / "settings.yaml",
        """mcp_servers:
  ${SERVER_NAME}:
    type: stdio
    command: ${COMMAND}
    args: ["${ARG}"]
    env:
      TOKEN: "prefix-${DEFINED_TOKEN}-${MISSING_TOKEN}"
    headers:
      Authorization: "Bearer ${DEFINED_TOKEN}"
""",
    )

    config = load_config(str(project))

    server = config.servers["${SERVER_NAME}"]
    assert server.command == "${COMMAND}"
    assert server.args == ["${ARG}"]
    assert server.env == {"TOKEN": "prefix-expanded-"}
    assert server.headers == {"Authorization": "Bearer expanded"}
    stderr = capsys.readouterr().err
    assert stderr.count("${MISSING_TOKEN}") == 1


@pytest.mark.parametrize(
    ("definition", "reason"),
    [
        ("command: python", "type"),
        ("type: invalid", "type"),
        ("type: stdio", "command"),
        ("type: http", "url"),
    ],
)
def test_invalid_server_is_skipped_without_hiding_valid_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    definition: str,
    reason: str,
) -> None:
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    indented = "\n".join(f"    {line}" for line in definition.splitlines())
    _write(
        project / ".Arkcode" / "settings.yaml",
        "mcp_servers:\n"
        f"  bad:\n{indented}\n"
        "  good:\n    type: stdio\n    command: python\n",
    )

    config = load_config(str(project))

    assert set(config.servers) == {"good"}
    stderr = capsys.readouterr().err
    assert "[mcp] warn: skip server bad" in stderr
    assert reason in stderr


def test_malformed_server_collection_is_treated_as_invalid_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    _write(project / ".Arkcode" / "settings.yaml", "mcp_servers: []\n")

    assert load_config(str(project)) == Config()
    assert "[mcp] warn: load" in capsys.readouterr().err


def test_documented_example_is_a_valid_three_server_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("GITHUB_TOKEN", "test-github-token")
    monkeypatch.setenv("EXAMPLE_TOKEN", "test-http-token")
    example = Path(__file__).parents[2] / "docs" / "mcp" / "mcp-servers.example.yaml"
    _write(
        project / ".Arkcode" / "settings.yaml",
        example.read_text(encoding="utf-8"),
    )

    config = load_config(str(project))

    assert set(config.servers) == {"github", "local-sqlite", "example-http"}


def test_legacy_project_config_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    _write(
        project / ".Arkcode.yaml",
        "mcp_servers:\n  legacy:\n    type: stdio\n    command: python\n",
    )

    assert load_config(str(project)) == Config()


def test_invalid_permissions_section_does_not_hide_valid_mcp_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    _write(
        project / ".Arkcode" / "settings.yaml",
        """permissions: invalid
mcp_servers:
  project-server:
    type: stdio
    command: python
""",
    )

    config = load_config(str(project))

    assert set(config.servers) == {"project-server"}


def test_server_config_defaults_and_ignores_unknown() -> None:
    config = ServerConfig.model_validate(
        {
            "type": "stdio",
            "command": "npx",
            "extra": 1,
        }
    )

    assert config.args == []
    assert config.env == {}
    assert config.url == ""
