"""Worktree 领域的数据模型与配置。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class WorktreeError(RuntimeError):
    """Worktree 领域错误基类。"""


class WorktreeIdentityError(WorktreeError):
    """manifest/仓库身份校验失败。"""


class WorktreeHasChangesError(WorktreeError):
    """存在未提交修改或新增 commit，拒绝删除。"""


class WorktreeConfigError(WorktreeError):
    """Worktree 配置不支持。"""


@dataclass(frozen=True, slots=True)
class WorktreeConfig:
    shared_readonly_dirs: tuple[str, ...] = ("node_modules", ".venv", "vendor")
    shared_writable_dirs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Worktree:
    """单个 Worktree 的元信息。"""

    name: str
    path: Path
    branch: str
    based_on: str
    base_commit: str
    created: datetime
    manual: bool
    owner_job_id: str


MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class WorktreeManifest:
    """ArkCode 侧持久化的 Worktree 身份信息。"""

    schema_version: int
    repo_id: str
    repo_common_dir: str
    name: str
    path: str
    branch: str
    base_ref: str
    base_commit: str
    created_at: str
    manual: bool
    owner_job_id: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> WorktreeManifest:
        if value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise WorktreeIdentityError("manifest schema 版本未知，拒绝恢复")
        try:
            return cls(
                schema_version=int(value["schema_version"]),
                repo_id=str(value["repo_id"]),
                repo_common_dir=str(value["repo_common_dir"]),
                name=str(value["name"]),
                path=str(value["path"]),
                branch=str(value["branch"]),
                base_ref=str(value.get("base_ref", "")),
                base_commit=str(value["base_commit"]),
                created_at=str(value.get("created_at", "")),
                manual=bool(value.get("manual", False)),
                owner_job_id=str(value.get("owner_job_id", "")),
            )
        except KeyError as exc:
            raise WorktreeIdentityError(
                f"manifest 缺少必需字段: {exc}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "repo_id": self.repo_id,
            "repo_common_dir": self.repo_common_dir,
            "name": self.name,
            "path": self.path,
            "branch": self.branch,
            "base_ref": self.base_ref,
            "base_commit": self.base_commit,
            "created_at": self.created_at,
            "manual": self.manual,
            "owner_job_id": self.owner_job_id,
        }


@dataclass(frozen=True, slots=True)
class WorktreeSession:
    """当前活跃的 Worktree 会话。"""

    original_cwd: str
    worktree_path: str
    worktree_name: str
    original_branch: str
    original_head_commit: str
    session_id: str
    hook_based: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> WorktreeSession:
        return cls(
            original_cwd=str(value.get("original_cwd", "")),
            worktree_path=str(value.get("worktree_path", "")),
            worktree_name=str(value.get("worktree_name", "")),
            original_branch=str(value.get("original_branch", "")),
            original_head_commit=str(value.get("original_head_commit", "")),
            session_id=str(value.get("session_id", "")),
            hook_based=bool(value.get("hook_based", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_cwd": self.original_cwd,
            "worktree_path": self.worktree_path,
            "worktree_name": self.worktree_name,
            "original_branch": self.original_branch,
            "original_head_commit": self.original_head_commit,
            "session_id": self.session_id,
            "hook_based": self.hook_based,
        }


class ExitAction(Enum):
    KEEP = "keep"
    REMOVE = "remove"


@dataclass(frozen=True, slots=True)
class ExitOptions:
    discard_changes: bool = False


@dataclass(frozen=True, slots=True)
class ExitReport:
    removed: bool
    path: str
    branch: str


@dataclass(frozen=True, slots=True)
class AutoCleanupReport:
    kept: bool
    path: str = ""
    branch: str = ""
    base_commit: str = ""
