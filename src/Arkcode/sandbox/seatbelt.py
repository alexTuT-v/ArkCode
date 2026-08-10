"""macOS Seatbelt（sandbox-exec）沙箱后端。"""

from __future__ import annotations

import shlex
from pathlib import Path

from . import Sandbox, SandboxConfig

_SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def _build_profile(config: SandboxConfig) -> str:
    rules = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow sysctl-read)",
        '(allow file-read* (subpath "/"))',
    ]
    for path in config.allow_write:
        resolved = str(Path(path).resolve())
        rules.append(f'(allow file-write* (subpath "{resolved}"))')
    for path in config.deny_write:
        resolved = str(Path(path).resolve())
        matcher = "subpath" if Path(resolved).is_dir() else "literal"
        rules.append(f'(deny file-write* ({matcher} "{resolved}"))')
    if config.network_enabled:
        rules.append("(allow network*)")
    else:
        rules.append("(deny network*)")
    return "\n".join(rules)


class SeatbeltSandbox(Sandbox):
    """基于 sandbox-exec 的内核级沙箱。"""

    def wrap(self, command: str, config: SandboxConfig) -> str:
        profile = _build_profile(config)
        return (
            f"{_SANDBOX_EXEC} -p {shlex.quote(profile)} bash -c {shlex.quote(command)}"
        )

    def available(self) -> bool:
        return Path(_SANDBOX_EXEC).is_file()
