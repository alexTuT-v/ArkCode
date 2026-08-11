"""WorktreeManager 生命周期测试。"""

import asyncio
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from Arkcode.worktrees import (
    ExitAction,
    ExitOptions,
    WorktreeHasChangesError,
    WorktreeIdentityError,
    WorktreeManager,
)


def run_git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.mark.asyncio
async def test_create_simple(git_repo: Path) -> None:
    manager = await WorktreeManager.open(git_repo)
    worktree = await manager.create("alice", "HEAD", manual=True)
    assert (git_repo / ".Arkcode" / "worktrees" / "alice").is_dir()
    assert worktree.branch == "worktree-alice"
    assert worktree.path == (git_repo / ".Arkcode" / "worktrees" / "alice").resolve()
    assert worktree.manual is True


@pytest.mark.asyncio
async def test_create_nested_flattens(git_repo: Path) -> None:
    manager = await WorktreeManager.open(git_repo)
    worktree = await manager.create("team/alice", "HEAD", manual=True)
    assert worktree.branch == "worktree-team+alice"
    assert (git_repo / ".Arkcode" / "worktrees" / "team+alice").is_dir()


@pytest.mark.asyncio
async def test_quick_recovery_does_not_call_git_add(git_repo: Path) -> None:
    manager = await WorktreeManager.open(git_repo)
    await manager.create("alice", "HEAD", manual=True)
    calls: list[tuple[str, ...]] = []

    class RecordingRunner:
        async def run(self, args, *, cwd, timeout=60.0):  # type: ignore[no-untyped-def]
            calls.append(tuple(args))
            return await manager._runner.run(args, cwd=cwd, timeout=timeout)

    reopened = await WorktreeManager.open(git_repo, runner=RecordingRunner())  # type: ignore[arg-type]
    assert [worktree.name for worktree in reopened.list()] == ["alice"]
    assert not any("add" in args for args in calls)


@pytest.mark.asyncio
async def test_quick_recovery_rejects_mismatched_manifest(git_repo: Path) -> None:
    manager = await WorktreeManager.open(git_repo)
    await manager.create("alice", "HEAD", manual=True)
    manifest_path = (
        git_repo / ".Arkcode" / "worktrees" / ".metadata" / "alice.json"
    )
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            '"repo_id": "',
            '"repo_id": "tampered-',
            1,
        ),
        encoding="utf-8",
    )
    reopened = await WorktreeManager.open(git_repo)
    with pytest.raises(WorktreeIdentityError):
        await reopened.create("alice", "HEAD", manual=True)


@pytest.mark.asyncio
async def test_enter_returns_session_without_changing_cwd(git_repo: Path) -> None:
    manager = await WorktreeManager.open(git_repo)
    await manager.create("alice", "HEAD", manual=True)
    before = Path.cwd()
    session = await manager.enter("alice")
    assert Path.cwd() == before
    assert session.worktree_name == "alice"
    assert session.worktree_path == str(
        (git_repo / ".Arkcode" / "worktrees" / "alice").resolve()
    )
    assert session.session_id


@pytest.mark.asyncio
async def test_remove_refuses_changes_and_discard_removes(git_repo: Path) -> None:
    manager = await WorktreeManager.open(git_repo)
    worktree = await manager.create("alice", "HEAD", manual=True)
    (worktree.path / "server.py").write_text("print('changed')\n", encoding="utf-8")
    with pytest.raises(WorktreeHasChangesError):
        await manager.remove("alice", ExitOptions())
    assert (git_repo / ".Arkcode" / "worktrees" / "alice").is_dir()

    report = await manager.remove("alice", ExitOptions(discard_changes=True))
    assert report.removed is True
    assert not (git_repo / ".Arkcode" / "worktrees" / "alice").exists()
    branch_exists = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/worktree-alice"],
        cwd=git_repo,
        capture_output=True,
    )
    assert branch_exists.returncode != 0


@pytest.mark.asyncio
async def test_auto_cleanup_manual_kept_temp_clean_removed(git_repo: Path) -> None:
    manager = await WorktreeManager.open(git_repo)
    await manager.create("manual-wt", "HEAD", manual=True)
    report = await manager.auto_cleanup("manual-wt")
    assert report.kept is True
    assert (git_repo / ".Arkcode" / "worktrees" / "manual-wt").is_dir()

    await manager.create(
        "agent-a1b2c3d",
        "HEAD",
        manual=False,
        owner_job_id="job-1",
    )
    clean = await manager.auto_cleanup("agent-a1b2c3d")
    assert clean.kept is False
    assert not (git_repo / ".Arkcode" / "worktrees" / "agent-a1b2c3d").exists()


@pytest.mark.asyncio
async def test_auto_cleanup_keeps_dirty_with_details(git_repo: Path) -> None:
    manager = await WorktreeManager.open(git_repo)
    worktree = await manager.create(
        "agent-a9f8e7d",
        "HEAD",
        manual=False,
        owner_job_id="job-2",
    )
    (worktree.path / "note.txt").write_text("dirty", encoding="utf-8")
    report = await manager.auto_cleanup("agent-a9f8e7d")
    assert report.kept is True
    assert report.path == str(worktree.path)
    assert report.branch == worktree.branch
    assert report.base_commit == worktree.base_commit


@pytest.mark.asyncio
async def test_exit_remove_and_session_cleared(git_repo: Path) -> None:
    manager = await WorktreeManager.open(git_repo)
    await manager.create("alice", "HEAD", manual=True)
    await manager.enter("alice")
    session_file = git_repo / ".Arkcode" / "worktree_session.json"
    assert session_file.is_file()

    report = await manager.exit(
        "alice",
        ExitAction.REMOVE,
        ExitOptions(discard_changes=True),
    )
    assert report.removed is True
    assert session_file.read_text(encoding="utf-8").strip() == "null"
    assert manager.current_session is None


@pytest.mark.asyncio
async def test_session_recovery_and_external_deletion(git_repo: Path) -> None:
    manager = await WorktreeManager.open(git_repo)
    await manager.create("alice", "HEAD", manual=True)
    await manager.enter("alice")

    reopened = await WorktreeManager.open(git_repo)
    assert reopened.current_session is not None
    assert reopened.current_session.worktree_name == "alice"

    import shutil

    shutil.rmtree(git_repo / ".Arkcode" / "worktrees" / "alice")
    reopened2 = await WorktreeManager.open(git_repo)
    assert reopened2.current_session is None
    assert (
        git_repo / ".Arkcode" / "worktree_session.json"
    ).read_text(encoding="utf-8").strip() == "null"


@pytest.mark.asyncio
async def test_sweep_stale_only_removes_old_temp(git_repo: Path) -> None:
    remote = git_repo.parent / "remote.git"
    remote.mkdir()
    run_git(remote, "init", "-q", "--bare")
    run_git(git_repo, "remote", "add", "origin", str(remote))
    run_git(git_repo, "push", "-qu", "origin", "main")
    manager = await WorktreeManager.open(git_repo)
    old = await manager.create(
        "agent-a1111111",
        "HEAD",
        manual=False,
        owner_job_id="job-1",
    )
    recent = await manager.create(
        "agent-b2222222",
        "HEAD",
        manual=False,
        owner_job_id="job-2",
    )
    old_time = datetime.now().astimezone() - timedelta(hours=48)
    os.utime(old.path, (old_time.timestamp(), old_time.timestamp()))

    removed = await manager.sweep_stale(
        datetime.now().astimezone() - timedelta(hours=24)
    )
    assert removed == [old.name]
    assert not old.path.exists()
    assert recent.path.exists()


@pytest.mark.asyncio
async def test_sweep_stale_skips_current_session(git_repo: Path) -> None:
    remote = git_repo.parent / "remote.git"
    remote.mkdir()
    run_git(remote, "init", "-q", "--bare")
    run_git(git_repo, "remote", "add", "origin", str(remote))
    run_git(git_repo, "push", "-qu", "origin", "main")
    manager = await WorktreeManager.open(git_repo)
    current = await manager.create(
        "agent-c3333333",
        "HEAD",
        manual=False,
        owner_job_id="job-3",
    )
    old_time = datetime.now().astimezone() - timedelta(hours=48)
    os.utime(current.path, (old_time.timestamp(), old_time.timestamp()))
    await manager.enter(current.name)
    removed = await manager.sweep_stale(
        datetime.now().astimezone() - timedelta(hours=24)
    )
    assert removed == []
    assert current.path.exists()


@pytest.mark.asyncio
async def test_concurrent_create_same_name_conflicts(git_repo: Path) -> None:
    manager = await WorktreeManager.open(git_repo)
    results = await asyncio.gather(
        manager.create("dup", "HEAD", manual=True),
        manager.create("dup", "HEAD", manual=True),
        return_exceptions=True,
    )
    successes = [item for item in results if not isinstance(item, Exception)]
    failures = [item for item in results if isinstance(item, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
