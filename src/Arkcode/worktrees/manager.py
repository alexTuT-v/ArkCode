"""Worktree 生命周期管理：创建、恢复、进入、退出、清理与 stale sweep。"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

from .changes import has_worktree_changes
from .git import GitRunner
from .manifest import ManifestStore, manifest_matches
from .models import (
    AutoCleanupReport,
    ExitAction,
    ExitOptions,
    ExitReport,
    Worktree,
    WorktreeConfig,
    WorktreeError,
    WorktreeHasChangesError,
    WorktreeIdentityError,
    WorktreeManifest,
    WorktreeSession,
)
from .session import WorktreeSessionStore
from .setup import load_worktree_config, perform_post_creation_setup
from .slug import flatten_slug, validate_slug

TEMP_NAME_RE = re.compile(r"^agent-a[0-9a-f]{7}$")


class WorktreeManager:
    """单仓库内 Worktree 的生命周期与状态所有者。"""

    def __init__(
        self,
        *,
        repo_root: Path,
        repo_common_dir: Path,
        repo_id: str,
        worktree_dir: Path,
        config: WorktreeConfig,
        runner: GitRunner,
        readonly_guaranteed: bool,
    ) -> None:
        self._repo_root = repo_root
        self._repo_common_dir = repo_common_dir
        self._repo_id = repo_id
        self._worktree_dir = worktree_dir
        self._metadata_dir = worktree_dir / ".metadata"
        self._metadata_dir.mkdir(parents=True, exist_ok=True)
        self._session_file = repo_root / ".Arkcode" / "worktree_session.json"
        self._config = config
        self._runner = runner
        self._readonly_guaranteed = readonly_guaranteed
        self._lock = asyncio.Lock()
        self._reservations: dict[str, str] = {}
        self._active: dict[str, Worktree] = {}
        self._current_session: WorktreeSession | None = None
        self._manifest_store = ManifestStore(self._metadata_dir, self._repo_id)
        self._session_store = WorktreeSessionStore(self._session_file)

    @classmethod
    async def open(
        cls,
        repo_root: str | Path,
        config: WorktreeConfig | None = None,
        *,
        runner: GitRunner | None = None,
        readonly_guaranteed: bool = False,
    ) -> WorktreeManager:
        """校验仓库身份并恢复 session 与 active 映射。"""

        git = runner or GitRunner()
        root = Path(repo_root).resolve()
        top = await git.run(["rev-parse", "--show-toplevel"], cwd=root)
        if not top.ok:
            raise WorktreeError(f"{root} 不是 git 仓库根目录")
        resolved_root = Path(top.stdout.strip()).resolve()
        common = await git.run(
            ["rev-parse", "--git-common-dir"],
            cwd=resolved_root,
        )
        if not common.ok:
            raise WorktreeError("无法解析 git-common-dir")
        common_dir = Path(common.stdout.strip())
        if not common_dir.is_absolute():
            common_dir = resolved_root / common_dir
        common_dir = common_dir.resolve()
        repo_id = hashlib.sha256(str(common_dir).encode()).hexdigest()[:16]
        worktree_dir = resolved_root / ".Arkcode" / "worktrees"
        worktree_dir.mkdir(parents=True, exist_ok=True)
        manager = cls(
            repo_root=resolved_root,
            repo_common_dir=common_dir,
            repo_id=repo_id,
            worktree_dir=worktree_dir,
            config=config or load_worktree_config(resolved_root),
            runner=git,
            readonly_guaranteed=readonly_guaranteed,
        )
        manager._restore_session()
        manager._scan_active()
        return manager

    def _restore_session(self) -> None:
        session = self._session_store.load()
        if session is None:
            return
        valid = False
        try:
            manifest = self._manifest_store.load(session.worktree_name)
            if (
                manifest is not None
                and manifest.repo_id == self._repo_id
                and manifest.path == str(Path(session.worktree_path).resolve())
                and Path(session.worktree_path).is_dir()
            ):
                valid = True
        except WorktreeIdentityError:
            valid = False
        if not valid:
            print("警告: session worktree invalid, cleared", file=sys.stderr)
            self._session_store.save(None)
            self._current_session = None
            return
        self._current_session = session

    def _scan_active(self) -> None:
        for manifest_path in sorted(self._metadata_dir.glob("*.json")):
            name = manifest_path.stem
            try:
                manifest = self._manifest_store.load(name)
                if manifest is None:
                    continue
                worktree = self._worktree_from_manifest(manifest)
            except WorktreeIdentityError as exc:
                print(f"警告: 跳过 Worktree {name}: {exc}", file=sys.stderr)
                continue
            if not worktree.path.is_dir():
                print(
                    f"警告: Worktree {name} 目录不存在，跳过恢复",
                    file=sys.stderr,
                )
                continue
            self._active[name] = worktree

    def _worktree_from_manifest(self, manifest: WorktreeManifest) -> Worktree:
        try:
            created = datetime.fromisoformat(manifest.created_at)
        except (ValueError, TypeError):
            created = datetime.now().astimezone()
        return Worktree(
            name=manifest.name,
            path=Path(manifest.path),
            branch=manifest.branch,
            based_on=manifest.base_ref,
            base_commit=manifest.base_commit,
            created=created,
            manual=manifest.manual,
            owner_job_id=manifest.owner_job_id,
        )

    async def create(
        self,
        name: str,
        base_ref: str = "HEAD",
        *,
        manual: bool,
        owner_job_id: str = "",
    ) -> Worktree:
        validate_slug(name)
        flat = flatten_slug(name)
        wt_path = (self._worktree_dir / flat).resolve()
        branch = f"worktree-{flat}"
        async with self._lock:
            if name in self._active:
                raise WorktreeError(f"Worktree 已存在: {name}")
            if name in self._reservations:
                raise WorktreeError(f"Worktree 正在创建: {name}")
            token = uuid.uuid4().hex
            self._reservations[name] = token
        try:
            if wt_path.exists():
                return await self._quick_recover(
                    name,
                    wt_path,
                    branch,
                    owner_job_id,
                    token,
                )
            base_result = await self._runner.run(
                ["rev-parse", base_ref],
                cwd=self._repo_root,
            )
            if not base_result.ok:
                raise WorktreeError(
                    f"无法解析 base 引用 {base_ref}: {base_result.stderr.strip()}"
                )
            base_commit = base_result.stdout.strip()
            add_result = await self._runner.run(
                [
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    str(wt_path),
                    base_commit,
                ],
                cwd=self._repo_root,
            )
            if not add_result.ok:
                raise WorktreeError(
                    f"git worktree add 失败: {add_result.stderr.strip()}"
                )
            await asyncio.sleep(0.1)
            await perform_post_creation_setup(
                self._repo_root,
                wt_path,
                self._runner,
                readonly_guaranteed=self._readonly_guaranteed,
            )
            created = datetime.now().astimezone()
            manifest = WorktreeManifest(
                schema_version=1,
                repo_id=self._repo_id,
                repo_common_dir=str(self._repo_common_dir),
                name=name,
                path=str(wt_path),
                branch=branch,
                base_ref=base_ref,
                base_commit=base_commit,
                created_at=created.isoformat(),
                manual=manual,
                owner_job_id=owner_job_id,
            )
            self._manifest_store.save(manifest)
            worktree = Worktree(
                name=name,
                path=wt_path,
                branch=branch,
                based_on=base_ref,
                base_commit=base_commit,
                created=created,
                manual=manual,
                owner_job_id=owner_job_id,
            )
            async with self._lock:
                if self._reservations.get(name) != token:
                    raise WorktreeError("创建期间发生并发冲突")
                self._active[name] = worktree
                del self._reservations[name]
            return worktree
        except Exception:
            async with self._lock:
                if self._reservations.get(name) == token:
                    del self._reservations[name]
            raise

    async def _quick_recover(
        self,
        name: str,
        wt_path: Path,
        branch: str,
        owner_job_id: str,
        token: str,
    ) -> Worktree:
        manifest = self._manifest_store.load(name)
        if manifest is None:
            raise WorktreeIdentityError(
                f"目录 {wt_path} 已存在但 manifest 缺失，拒绝恢复"
            )
        if not manifest_matches(
            manifest,
            wt_path=str(wt_path),
            branch=branch,
            base_commit=manifest.base_commit,
            owner_job_id=owner_job_id,
        ):
            raise WorktreeIdentityError(
                f"manifest 与目录身份不匹配，拒绝恢复 {name}"
            )
        git_file = wt_path / ".git"
        if not git_file.exists():
            raise WorktreeIdentityError(f"{wt_path} 缺少 .git 指针")
        head = wt_path / "HEAD"
        if head.is_file() and head.read_text(encoding="utf-8").strip() != (
            f"ref: refs/heads/{branch}"
        ):
            raise WorktreeIdentityError(f"{name} 的 HEAD 不在预期分支 {branch}")
        worktree = self._worktree_from_manifest(manifest)
        async with self._lock:
            if self._reservations.get(name) == token:
                del self._reservations[name]
            self._active[name] = worktree
        return worktree

    async def enter(self, name: str) -> WorktreeSession:
        async with self._lock:
            worktree = self._active.get(name)
            if worktree is None:
                raise WorktreeError(f"未知 Worktree: {name}")
            branch_result = await self._runner.run(
                ["symbolic-ref", "--short", "HEAD"],
                cwd=self._repo_root,
            )
            original_branch = (
                branch_result.stdout.strip() if branch_result.ok else ""
            )
            head_result = await self._runner.run(
                ["rev-parse", "HEAD"],
                cwd=self._repo_root,
            )
            original_head = head_result.stdout.strip() if head_result.ok else ""
            session = WorktreeSession(
                original_cwd=str(Path.cwd()),
                worktree_path=str(worktree.path),
                worktree_name=name,
                original_branch=original_branch,
                original_head_commit=original_head,
                session_id=uuid.uuid4().hex,
            )
            self._current_session = session
            self._session_store.save(session)
            return session

    async def _exit_common(
        self,
        name: str,
        action: ExitAction,
        options: ExitOptions,
        *,
        require_current: bool,
    ) -> ExitReport:
        async with self._lock:
            worktree = self._active.get(name)
            if worktree is None:
                raise WorktreeError(f"未知 Worktree: {name}")
            if (
                require_current
                and self._current_session is not None
                and self._current_session.worktree_name != name
            ):
                raise WorktreeError(f"只能退出当前 session 的 Worktree: {name}")
            if (
                action is ExitAction.REMOVE
                and not options.discard_changes
                and await has_worktree_changes(
                    self._runner,
                    str(worktree.path),
                    worktree.base_commit,
                )
            ):
                raise WorktreeHasChangesError(
                    f"Worktree {name} 存在未提交修改或新增 commit，拒绝删除"
                )
            removed = False
            if action is ExitAction.REMOVE:
                remove_result = await self._runner.run(
                    ["worktree", "remove", "--force", str(worktree.path)],
                    cwd=self._repo_root,
                )
                if not remove_result.ok:
                    raise WorktreeError(
                        f"git worktree remove 失败: {remove_result.stderr.strip()}"
                    )
                await asyncio.sleep(0.1)
                await self._runner.run(
                    ["branch", "-D", worktree.branch],
                    cwd=self._repo_root,
                )
                self._manifest_store.remove(name)
                del self._active[name]
                removed = True
            if self._current_session is not None and (
                self._current_session.worktree_name == name or require_current
            ):
                self._current_session = None
                self._session_store.save(None)
            return ExitReport(
                removed=removed,
                path=str(worktree.path),
                branch=worktree.branch,
            )

    async def exit(
        self,
        name: str,
        action: ExitAction,
        options: ExitOptions,
    ) -> ExitReport:
        return await self._exit_common(
            name,
            action,
            options,
            require_current=True,
        )

    async def remove(
        self,
        name: str,
        options: ExitOptions,
    ) -> ExitReport:
        return await self._exit_common(
            name,
            ExitAction.REMOVE,
            options,
            require_current=False,
        )

    async def auto_cleanup(self, name: str) -> AutoCleanupReport:
        worktree = self._active.get(name)
        if worktree is None:
            return AutoCleanupReport(kept=True)
        if worktree.manual:
            return AutoCleanupReport(
                kept=True,
                path=str(worktree.path),
                branch=worktree.branch,
                base_commit=worktree.base_commit,
            )
        if await has_worktree_changes(
            self._runner,
            str(worktree.path),
            worktree.base_commit,
        ):
            return AutoCleanupReport(
                kept=True,
                path=str(worktree.path),
                branch=worktree.branch,
                base_commit=worktree.base_commit,
            )
        await self.remove(name, ExitOptions(discard_changes=True))
        return AutoCleanupReport(kept=False)

    async def sweep_stale(self, cutoff: datetime) -> list[str]:
        removed: list[str] = []
        if not self._worktree_dir.is_dir():
            return removed
        for directory in sorted(self._worktree_dir.iterdir()):
            if not directory.is_dir() or directory.name == ".metadata":
                continue
            if TEMP_NAME_RE.fullmatch(directory.name) is None:
                continue
            try:
                mtime = datetime.fromtimestamp(directory.stat().st_mtime).astimezone()
            except OSError:
                continue
            if mtime > cutoff:
                continue
            if (
                self._current_session is not None
                and Path(self._current_session.worktree_path) == directory
            ):
                continue
            name = directory.name
            try:
                manifest = self._manifest_store.load(name)
                if manifest is None or manifest.repo_id != self._repo_id:
                    continue
                if await has_worktree_changes(
                    self._runner,
                    str(directory),
                    manifest.base_commit,
                ):
                    continue
                unpushed = await self._runner.run(
                    [
                        "rev-list",
                        "--max-count=1",
                        "HEAD",
                        "--not",
                        "--remotes",
                    ],
                    cwd=directory,
                )
                if unpushed.ok and unpushed.stdout.strip():
                    continue
            except WorktreeIdentityError:
                continue
            try:
                await self.remove(name, ExitOptions(discard_changes=True))
                removed.append(name)
            except WorktreeError:
                continue
        return removed

    def list(self) -> list[Worktree]:
        return list(self._active.values())

    @property
    def current_session(self) -> WorktreeSession | None:
        return self._current_session

    @property
    def repo_root(self) -> Path:
        return self._repo_root
