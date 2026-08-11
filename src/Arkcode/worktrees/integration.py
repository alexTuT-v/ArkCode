"""SubAgent 的 Worktree EnvironmentPreparer 适配。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..subagents.models import (
    BackgroundTask,
    CleanupReport,
    EnvironmentPreparer,
    PreparedEnvironment,
    RunResult,
)
from ..tools.workspace import ExecutionPathContext
from .manager import WorktreeManager

if TYPE_CHECKING:
    pass


def build_worktree_notice(parent_cwd: str, wt_path: str) -> str:
    return (
        "<worktree-context>\n"
        "你当前在一个独立的 Git Worktree 副本中工作，与父 Agent 隔离。\n"
        f"- 父目录: {parent_cwd}\n"
        f"- 你的工作目录: {wt_path}\n"
        "- 父 Agent 提到的绝对路径基于父目录，你需要翻译成本地路径（替换前缀）再读写\n"
        "- 编辑文件前，必须先在本地 Worktree 重新 read_file 一次，避免使用过时内容\n"
        "</worktree-context>"
    )


class WorktreeEnvironmentPreparer(EnvironmentPreparer):
    """create → workspace_scope → run → auto_cleanup 的所有权链。"""

    def __init__(
        self,
        manager: WorktreeManager,
        *,
        readonly_guaranteed: bool = False,
    ) -> None:
        self._manager = manager
        self._readonly_guaranteed = readonly_guaranteed

    async def prepare(self, job: BackgroundTask) -> PreparedEnvironment:
        import secrets

        name = f"agent-a{secrets.token_hex(4)[:7]}"
        worktree = await self._manager.create(
            name,
            "HEAD",
            manual=False,
            owner_job_id=job.id,
        )
        job.worktree_name = worktree.name
        job.worktree_path = str(worktree.path)
        job.worktree_branch = worktree.branch
        job.worktree_base_commit = worktree.base_commit
        context = ExecutionPathContext.at(worktree.path)
        notice = build_worktree_notice(
            str(self._manager.repo_root),
            str(worktree.path),
        )
        return PreparedEnvironment(workspace=context, reminder=notice)

    async def cleanup(
        self,
        job: BackgroundTask,
        outcome: RunResult | None,
    ) -> CleanupReport:
        report = await self._manager.auto_cleanup(job.worktree_name)
        if report.kept:
            job.worktree_path = report.path
            job.worktree_branch = report.branch
            job.worktree_base_commit = report.base_commit
            return CleanupReport(
                kept=True,
                path=report.path,
                branch=report.branch,
                base_commit=report.base_commit,
            )
        return CleanupReport(kept=False)
