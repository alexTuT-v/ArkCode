"""Worktree 变更检测（fail-closed）。"""

from __future__ import annotations

from .git import GitRunner


async def has_worktree_changes(
    runner: GitRunner,
    wt_path: str,
    base_commit: str,
) -> bool:
    """status 非空或有新增 commit 视为有变更；git 失败也 fail-closed。"""

    try:
        status = await runner.run(["status", "--porcelain"], cwd=wt_path)
        if not status.ok or status.stdout.strip():
            return True
        count = await runner.run(
            ["rev-list", "--count", f"{base_commit}..HEAD"],
            cwd=wt_path,
        )
        if not count.ok:
            return True
        return int(count.stdout.strip() or "0") > 0
    except Exception:
        return True
