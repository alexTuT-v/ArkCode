"""测试共享 fixture。"""

import subprocess
from pathlib import Path

import pytest


def run_git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """创建一个已初始化且有一个提交的临时 Git 仓库。"""

    root = tmp_path / "repo"
    root.mkdir()
    run_git(root, "init", "-q", "-b", "main")
    run_git(root, "config", "user.email", "test@example.com")
    run_git(root, "config", "user.name", "Test")
    (root / "server.py").write_text("print('ok')\n", encoding="utf-8")
    run_git(root, "add", ".")
    run_git(root, "commit", "-qm", "init")
    return root
