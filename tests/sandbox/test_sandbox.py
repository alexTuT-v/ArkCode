"""sandbox 抽象、工厂与平台后端测试。"""

from Arkcode.sandbox import SandboxConfig, create_sandbox
from Arkcode.sandbox.bwrap import BwrapSandbox
from Arkcode.sandbox.seatbelt import SeatbeltSandbox


def test_bwrap_wrap_builds_isolated_command() -> None:
    sandbox = BwrapSandbox()
    config = SandboxConfig(
        allow_write=["/workspace"],
        deny_write=["/workspace/.Arkcode/config.yaml"],
        network_enabled=False,
    )

    wrapped = sandbox.wrap("git status", config)

    assert wrapped.startswith("bwrap --unshare-user --unshare-pid --ro-bind / /")
    assert "--bind /workspace /workspace" in wrapped
    assert (
        "--ro-bind /workspace/.Arkcode/config.yaml "
        "/workspace/.Arkcode/config.yaml" in wrapped
    )
    assert "--unshare-net" in wrapped
    assert wrapped.endswith("-- bash -c 'git status'")


def test_bwrap_network_enabled_omits_unshare_net() -> None:
    wrapped = BwrapSandbox().wrap("true", SandboxConfig(network_enabled=True))

    assert "--unshare-net" not in wrapped


def test_seatbelt_profile_denies_default_and_allows_write() -> None:
    sandbox = SeatbeltSandbox()
    config = SandboxConfig(
        allow_write=["/workspace"],
        deny_write=["/workspace/.Arkcode/config.yaml"],
        network_enabled=False,
    )

    wrapped = sandbox.wrap("make test", config)

    assert wrapped.startswith("/usr/bin/sandbox-exec -p")
    assert "(deny default)" in wrapped
    assert '(allow file-write* (subpath "/workspace"))' in wrapped
    assert '(deny file-write* (literal "/workspace/.Arkcode/config.yaml"))' in wrapped
    assert "(deny network*)" in wrapped


def test_create_sandbox_returns_none_on_unknown_platform(monkeypatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")

    assert create_sandbox() is None
