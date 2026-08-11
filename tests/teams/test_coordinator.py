"""Coordinator Mode 双锁与精确白名单测试。"""


from Arkcode.config import Config, Features
from Arkcode.teams.coordinator import (
    COORDINATOR_ALLOWED_TOOLS,
    env_truthy,
    is_enabled,
)


def config(coordinator: bool = False) -> Config:
    return Config(providers=[], features=Features(coordinator_mode=coordinator))


def test_env_truthy() -> None:
    assert env_truthy("1")
    assert env_truthy("true")
    assert env_truthy("YES")
    assert not env_truthy("")
    assert not env_truthy("0")


def test_coordinator_requires_both_locks(monkeypatch) -> None:
    monkeypatch.delenv("ArkCODE_COORDINATOR_MODE", raising=False)
    assert not is_enabled(config(coordinator=True))
    monkeypatch.setenv("ArkCODE_COORDINATOR_MODE", "1")
    assert is_enabled(config(coordinator=True))
    assert not is_enabled(config(coordinator=False))


def test_allowed_tools_are_exact() -> None:
    assert COORDINATOR_ALLOWED_TOOLS == frozenset(
        {"Agent", "SendMessage", "JobStop", "TeamDelete"}
    )
    for excluded in (
        "write_file",
        "edit_file",
        "bash",
        "read_file",
        "glob",
        "grep",
        "TeamCreate",
        "TaskCreate",
    ):
        assert excluded not in COORDINATOR_ALLOWED_TOOLS
