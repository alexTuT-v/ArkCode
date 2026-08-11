"""Manifest 原子存储与身份校验测试。"""

import json
from pathlib import Path

import pytest

from Arkcode.worktrees.manifest import (
    ManifestStore,
    atomic_write_json,
    manifest_matches,
)
from Arkcode.worktrees.models import (
    WorktreeIdentityError,
    WorktreeManifest,
)


def make_manifest(**overrides: object) -> WorktreeManifest:
    values = {
        "schema_version": 1,
        "repo_id": "abc123",
        "repo_common_dir": "/repo/.git",
        "name": "alice",
        "path": "/repo/.Arkcode/worktrees/alice",
        "branch": "worktree-alice",
        "base_ref": "HEAD",
        "base_commit": "deadbeef",
        "created_at": "2026-01-01T00:00:00+00:00",
        "manual": True,
        "owner_job_id": "",
    }
    values.update(overrides)
    return WorktreeManifest(**values)  # type: ignore[arg-type]


def test_manifest_roundtrip(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path, "abc123")
    store.save(make_manifest())
    loaded = store.load("alice")
    assert loaded is not None
    assert loaded.branch == "worktree-alice"
    assert loaded.repo_id == "abc123"


def test_manifest_atomic_write_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    atomic_write_json(target, {"a": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    assert list(tmp_path.glob(".tmp-*")) == []


def test_manifest_schema_mismatch_rejected(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path, "abc123")
    store.save(make_manifest(schema_version=99))
    with pytest.raises(WorktreeIdentityError):
        store.load("alice")


def test_manifest_repo_id_mismatch_rejected(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path, "other-id")
    store.save(make_manifest(repo_id="abc123"))
    with pytest.raises(WorktreeIdentityError):
        store.load("alice")


def test_manifest_corrupt_fail_closed(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path, "abc123")
    (tmp_path / "alice.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(WorktreeIdentityError):
        store.load("alice")


def test_manifest_remove(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path, "abc123")
    store.save(make_manifest())
    store.remove("alice")
    assert store.load("alice") is None


def test_manifest_matches_requires_full_identity() -> None:
    manifest = make_manifest()
    assert manifest_matches(
        manifest,
        wt_path="/repo/.Arkcode/worktrees/alice",
        branch="worktree-alice",
        base_commit="deadbeef",
        owner_job_id="",
    )
    assert not manifest_matches(
        manifest,
        wt_path="/other/.Arkcode/worktrees/alice",
        branch="worktree-alice",
        base_commit="deadbeef",
        owner_job_id="",
    )
    assert not manifest_matches(
        manifest,
        wt_path="/repo/.Arkcode/worktrees/alice",
        branch="worktree-bob",
        base_commit="deadbeef",
        owner_job_id="",
    )
