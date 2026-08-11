"""创建后三步设置与 hooks 跳过测试。"""

import subprocess
from pathlib import Path

import pytest

from Arkcode.worktrees.git import GitRunner
from Arkcode.worktrees.setup import (
    load_worktree_config,
    perform_post_creation_setup,
)


def run_git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.mark.asyncio
async def test_setup_copies_local_config(git_repo: Path) -> None:
    arkcode_dir = git_repo / ".Arkcode"
    arkcode_dir.mkdir()
    (arkcode_dir / "settings.local.yaml").write_text(
        "permissions:\n  allow: []\n",
        encoding="utf-8",
    )
    wt = git_repo / "wt"
    wt.mkdir()
    await perform_post_creation_setup(
        git_repo,
        wt,
        GitRunner(),
        readonly_guaranteed=False,
    )
    assert (wt / ".Arkcode" / "settings.local.yaml").is_file()


@pytest.mark.asyncio
async def test_setup_never_touches_hooks(git_repo: Path) -> None:
    before = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=git_repo,
        capture_output=True,
    )
    wt = git_repo / "wt"
    wt.mkdir()
    calls: list[list[str]] = []

    class RecordingRunner(GitRunner):
        async def run(self, args, *, cwd, timeout=60.0):  # type: ignore[override]
            calls.append(list(args))
            return await super().run(args, cwd=cwd, timeout=timeout)

    await perform_post_creation_setup(
        git_repo,
        wt,
        RecordingRunner(),
        readonly_guaranteed=False,
    )
    assert not any(
        "husky" in item or "core.hooksPath" in item for args in calls for item in args
    )
    after = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=git_repo,
        capture_output=True,
    )
    assert before.returncode == after.returncode


@pytest.mark.asyncio
async def test_readonly_symlink_only_when_guaranteed(
    git_repo: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (git_repo / "node_modules").mkdir()
    (git_repo / "node_modules" / "dep.txt").write_text("x", encoding="utf-8")
    wt = git_repo / "wt"
    wt.mkdir()
    await perform_post_creation_setup(
        git_repo,
        wt,
        GitRunner(),
        readonly_guaranteed=True,
    )
    assert (wt / "node_modules").is_symlink()
    assert (wt / "node_modules" / "dep.txt").read_text(encoding="utf-8") == "x"

    wt2 = git_repo / "wt2"
    wt2.mkdir()
    await perform_post_creation_setup(
        git_repo,
        wt2,
        GitRunner(),
        readonly_guaranteed=False,
    )
    assert not (wt2 / "node_modules").exists()
    assert "跳过 readonly symlink" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_worktreeinclude_copies_ignored_files(git_repo: Path) -> None:
    (git_repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    (git_repo / ".worktreeinclude").write_text("*.env\n", encoding="utf-8")
    (git_repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    wt = git_repo / "wt"
    wt.mkdir()
    await perform_post_creation_setup(
        git_repo,
        wt,
        GitRunner(),
        readonly_guaranteed=False,
    )
    assert (wt / ".env").read_text(encoding="utf-8") == "SECRET=1\n"


def test_writable_shared_dirs_rejected(tmp_path: Path) -> None:
    arkcode = tmp_path / ".Arkcode"
    arkcode.mkdir()
    (arkcode / "worktree.yaml").write_text(
        "shared_writable_dirs:\n  - shared\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        load_worktree_config(tmp_path)
