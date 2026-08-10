"""权限核心五层之前的判定与配置测试。"""

import json
from pathlib import Path

import pytest

from Arkcode.llm import ToolCall
from Arkcode.permissions import Category, Decision, Mode, new_engine, parse_mode
from Arkcode.permissions.blacklist import hits_blacklist
from Arkcode.permissions.engine import mode_fallback
from Arkcode.permissions.rules import Rule, RuleSet, match_pattern, parse_rule
from Arkcode.permissions.sandbox import sandbox_ok
from Arkcode.permissions.settings import (
    SettingsError,
    extract_target,
    friendly_name,
    load_settings,
)


def call(name: str, value: dict[str, str] | str) -> ToolCall:
    payload = value if isinstance(value, str) else json.dumps(value)
    return ToolCall("call", name, payload)


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -fr ~",
        ":(){ :|:& };:",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sda",
    ],
)
def test_blacklist_rejects_dangerous_commands(command: str) -> None:
    assert hits_blacklist(command)


@pytest.mark.parametrize("command", ["rm -rf ./build", "git status", "ls -la"])
def test_blacklist_does_not_reject_normal_commands(command: str) -> None:
    assert not hits_blacklist(command)


def test_blacklist_and_sandbox_are_denied_even_in_bypass(tmp_path: Path) -> None:
    engine, error = new_engine(str(tmp_path))

    assert error is None
    assert (
        engine.check(Mode.BYPASS, call("bash", {"command": "rm -rf /"}), False)[0]
        is Decision.DENY
    )
    assert (
        engine.check(Mode.BYPASS, call("read_file", {"path": "/etc/passwd"}), True)[0]
        is Decision.DENY
    )
    assert (
        engine.check(Mode.BYPASS, call("write_file", {"path": "new/a.txt"}), False)[0]
        is Decision.ALLOW
    )


def test_sandbox_resolves_symlink_and_missing_ancestors(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    assert sandbox_ok(str(root.resolve()), "new/a/b.txt")
    assert not sandbox_ok(str(root.resolve()), "escape/secret.txt")
    assert not sandbox_ok(str(root.resolve()), "../outside/secret.txt")


def test_rules_parse_match_and_deny_wins() -> None:
    parsed, ok = parse_rule("Bash(git *)")
    rules = RuleSet(
        allow=[parsed, Rule("Write", "src/**", True)],
        deny=[Rule("Bash", "git push", False)],
    )

    assert ok
    assert match_pattern("git *", "git status")
    assert match_pattern("src/**", "src/a/b.py")
    assert not match_pattern("src/**", "docs/x")
    assert rules.match("Bash", "git push") == (Decision.DENY, True)
    assert rules.match("Bash", "git status") == (Decision.ALLOW, True)


def test_mode_matrix_and_safe_defaults(tmp_path: Path) -> None:
    assert mode_fallback(Mode.DEFAULT, Category.READ) is Decision.ALLOW
    assert mode_fallback(Mode.DEFAULT, Category.WRITE) is Decision.ASK
    assert mode_fallback(Mode.ACCEPT_EDITS, Category.WRITE) is Decision.ALLOW
    assert mode_fallback(Mode.ACCEPT_EDITS, Category.EXEC) is Decision.ASK
    assert mode_fallback(Mode.PLAN, Category.WRITE) is Decision.ASK
    assert mode_fallback(Mode.BYPASS, Category.EXEC) is Decision.ALLOW
    engine, _ = new_engine(str(tmp_path))
    assert engine.check(Mode.DEFAULT, call("unknown", {}), False)[0] is Decision.ASK
    assert (
        engine.check(Mode.DEFAULT, call("write_file", "{"), False)[0] is Decision.DENY
    )


def test_config_precedence_degradation_and_persistence(tmp_path: Path) -> None:
    config = tmp_path / ".Arkcode"
    config.mkdir()
    (config / "settings.yaml").write_text(
        "default_mode: acceptEdits\npermissions:\n  allow: ['Bash(git *)']\n",
        encoding="utf-8",
    )
    (config / "settings.local.yaml").write_text(
        "default_mode: plan\npermissions:\n  deny: ['Bash(git push)']\n",
        encoding="utf-8",
    )
    engine, error = new_engine(str(tmp_path))

    assert error is None
    assert engine.start_mode() is Mode.PLAN
    assert (
        engine.check(Mode.BYPASS, call("bash", {"command": "git push"}), False)[0]
        is Decision.DENY
    )
    engine.persist_local_allow(call("bash", {"command": "pytest -q"}))
    reloaded, _ = new_engine(str(tmp_path))
    assert (
        reloaded.check(Mode.DEFAULT, call("bash", {"command": "pytest -q"}), False)[0]
        is Decision.ALLOW
    )


def test_cross_layer_deny_wins_and_persisted_glob_is_exact(tmp_path: Path) -> None:
    config = tmp_path / ".Arkcode"
    config.mkdir()
    (config / "settings.yaml").write_text(
        "permissions:\n  deny: ['Bash(git push)']\n",
        encoding="utf-8",
    )
    (config / "settings.local.yaml").write_text(
        "permissions:\n  allow: ['Bash(git *)']\n",
        encoding="utf-8",
    )
    engine, _ = new_engine(str(tmp_path))

    assert (
        engine.check(Mode.BYPASS, call("bash", {"command": "git push"}), False)[0]
        is Decision.DENY
    )

    starred = call("bash", {"command": "printf '*'"})
    engine.persist_local_allow(starred)
    reloaded, _ = new_engine(str(tmp_path))
    assert reloaded.check(Mode.DEFAULT, starred, False)[0] is Decision.ALLOW
    assert (
        reloaded.check(
            Mode.DEFAULT,
            call("bash", {"command": "printf 'anything'"}),
            False,
        )[0]
        is Decision.ASK
    )


def test_cross_layer_ask_wins_over_allow(tmp_path: Path) -> None:
    config = tmp_path / ".Arkcode"
    config.mkdir()
    (config / "settings.yaml").write_text(
        "permissions:\n  ask: ['Bash(git push)']\n",
        encoding="utf-8",
    )
    (config / "settings.local.yaml").write_text(
        "permissions:\n  allow: ['Bash(git *)']\n",
        encoding="utf-8",
    )
    engine, _ = new_engine(str(tmp_path))

    assert (
        engine.check(Mode.BYPASS, call("bash", {"command": "git push"}), False)[0]
        is Decision.ASK
    )


def test_mode_and_tool_mappings() -> None:
    assert parse_mode("BYPASSPERMISSIONS") == (Mode.BYPASS, True)
    assert parse_mode("bad") == (Mode.DEFAULT, False)
    assert friendly_name("edit_file") == "Edit"
    assert extract_target(call("grep", {"pattern": "x"})) == (".", True, True)


def test_settings_error_degrades_without_losing_other_layers(tmp_path: Path) -> None:
    config = tmp_path / ".Arkcode"
    config.mkdir()
    project = config / "settings.yaml"
    local = config / "settings.local.yaml"
    project.write_text(
        "default_mode: acceptEdits\npermissions:\n  allow: ['Bash(git status)']\n",
        encoding="utf-8",
    )
    local.write_text("permissions: [broken", encoding="utf-8")

    with pytest.raises(SettingsError):
        load_settings(str(local))
    engine, error = new_engine(str(tmp_path))

    assert error is None
    assert engine.start_mode() is Mode.ACCEPT_EDITS
    assert (
        engine.check(Mode.DEFAULT, call("bash", {"command": "git status"}), False)[0]
        is Decision.ALLOW
    )


def test_invalid_mcp_section_does_not_hide_valid_project_permissions(
    tmp_path: Path,
) -> None:
    config = tmp_path / ".Arkcode"
    config.mkdir()
    (config / "settings.yaml").write_text(
        "default_mode: acceptEdits\n"
        "permissions:\n  allow: ['Bash(git status)']\n"
        "mcp_servers: []\n",
        encoding="utf-8",
    )

    engine, error = new_engine(str(tmp_path))

    assert error is None
    assert engine.start_mode() is Mode.ACCEPT_EDITS
    assert (
        engine.check(Mode.DEFAULT, call("bash", {"command": "git status"}), False)[0]
        is Decision.ALLOW
    )


def test_engine_creation_failure_returns_safe_engine(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    engine, error = new_engine(str(missing))

    assert error is not None
    assert engine.root == str(missing)
    assert engine.start_mode() is Mode.DEFAULT


@pytest.mark.parametrize(
    ("internal", "friendly"),
    [
        ("bash", "Bash"),
        ("read_file", "Read"),
        ("write_file", "Write"),
        ("edit_file", "Edit"),
        ("glob", "Glob"),
        ("grep", "Grep"),
    ],
)
def test_all_core_tools_have_friendly_names(internal: str, friendly: str) -> None:
    assert friendly_name(internal) == friendly


def test_mcp_namespaced_rules_support_exact_and_server_wildcard(
    tmp_path: Path,
) -> None:
    config = tmp_path / ".Arkcode"
    config.mkdir()
    (config / "settings.yaml").write_text(
        "permissions:\n"
        "  allow: ['mcp__github__*']\n"
        "  deny: ['mcp__github__delete_repo']\n",
        encoding="utf-8",
    )
    engine, error = new_engine(str(tmp_path))

    assert error is None
    assert (
        engine.check(Mode.DEFAULT, call("mcp__github__list_issues", {}), False)[0]
        is Decision.ALLOW
    )
    assert (
        engine.check(Mode.BYPASS, call("mcp__github__delete_repo", {}), False)[0]
        is Decision.DENY
    )


def test_mcp_permission_fallback_and_persisted_allow(tmp_path: Path) -> None:
    engine, error = new_engine(str(tmp_path))
    remote = call("mcp__demo__echo", {"value": "hello"})

    assert error is None
    assert engine.check(Mode.DEFAULT, remote, True)[0] is Decision.ALLOW
    assert engine.check(Mode.DEFAULT, remote, False)[0] is Decision.ASK
    assert engine.check(Mode.BYPASS, remote, False)[0] is Decision.ALLOW

    engine.persist_local_allow(remote)
    reloaded, _ = new_engine(str(tmp_path))
    assert reloaded.check(Mode.DEFAULT, remote, False)[0] is Decision.ALLOW
