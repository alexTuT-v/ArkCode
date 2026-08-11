"""Linux bubblewrap（bwrap）沙箱后端。"""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path

from . import Sandbox, SandboxConfig


class BwrapSandbox(Sandbox):
    """通过 bwrap 创建隔离用户命名空间，根文件系统只读。"""

    def wrap(self, command: str, config: SandboxConfig) -> str:
        args = [
            "bwrap",
            "--unshare-user",
            "--unshare-pid",
            "--ro-bind",
            "/",
            "/",
        ]
        for path in config.allow_write:
            resolved = str(Path(path).resolve())
            args.extend(["--bind", resolved, resolved])
        for path in config.deny_write:
            resolved = str(Path(path).resolve())
            args.extend(["--ro-bind", resolved, resolved])
        if not config.network_enabled:
            args.append("--unshare-net")
        args.extend(["--proc", "/proc", "--dev", "/dev", "--"])
        args.extend(["bash", "-c", command])
        return " ".join(shlex.quote(part) for part in args)

    def available(self) -> bool:
        return shutil.which("bwrap") is not None
