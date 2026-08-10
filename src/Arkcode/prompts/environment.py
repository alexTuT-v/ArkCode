"""运行环境采集与渲染。"""

import datetime as dt
import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Environment:
    """不进入稳定缓存块的运行时环境信息。"""

    working_dir: str
    platform: str
    date: str
    git_status: str
    version: str
    model: str

    def render(self) -> str:
        """渲染非空字段，避免意外暴露环境变量。"""

        fields = (
            ("Working directory", self.working_dir),
            ("Platform", self.platform),
            ("Date", self.date),
            ("Git status", self.git_status),
            ("Version", self.version),
            ("Model", self.model),
        )
        lines = [f"{name}: {value}" for name, value in fields if value]
        return "Environment:\n" + "\n".join(lines) if lines else ""


def _git_status(cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    changes = result.stdout.splitlines()
    return f"{len(changes)} files changed" if changes else "clean"


def gather_environment(version: str, model: str) -> Environment:
    """快速采集环境；git 不可用时仅省略该字段。"""

    try:
        cwd = os.getcwd()
    except OSError:
        cwd = ""
    return Environment(
        working_dir=cwd,
        platform=sys.platform,
        date=dt.date.today().isoformat(),
        git_status=_git_status(cwd) if cwd else "",
        version=version,
        model=model,
    )
