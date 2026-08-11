"""Manifest 原子存储与 fail-closed 身份校验。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import (
    MANIFEST_SCHEMA_VERSION,
    WorktreeIdentityError,
    WorktreeManifest,
)


class ManifestStore:
    def __init__(self, metadata_dir: str | Path, repo_id: str) -> None:
        self._directory = Path(metadata_dir)
        self._repo_id = repo_id

    def _path(self, name: str) -> Path:
        return self._directory / f"{name}.json"

    def save(self, manifest: WorktreeManifest) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._path(manifest.name), manifest.to_dict())

    def load(self, name: str) -> WorktreeManifest | None:
        path = self._path(name)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            raise WorktreeIdentityError(f"manifest 损坏: {path}")
        if not isinstance(value, dict):
            raise WorktreeIdentityError(f"manifest 格式非法: {path}")
        manifest = WorktreeManifest.from_dict(value)
        if manifest.repo_id != self._repo_id:
            raise WorktreeIdentityError("manifest 的 repo_id 与当前仓库不匹配")
        return manifest

    def remove(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)


def atomic_write_json(path: Path, value: Any) -> None:
    """唯一临时文件 + flush/fsync/os.replace 原子写。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".tmp-",
            suffix=".json",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def manifest_matches(
    manifest: WorktreeManifest,
    *,
    wt_path: str,
    branch: str,
    base_commit: str,
    owner_job_id: str,
) -> bool:
    """身份完全匹配才允许快速恢复。"""

    return (
        manifest.schema_version == MANIFEST_SCHEMA_VERSION
        and manifest.path == str(Path(wt_path).resolve())
        and manifest.branch == branch
        and manifest.base_commit == base_commit
        and manifest.owner_job_id == owner_job_id
    )
