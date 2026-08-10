"""格式 v2 会话元数据存储测试。"""

import json
import os
from pathlib import Path

import pytest

from Arkcode.sessions.meta import SessionMeta, SessionMetaStore


def test_meta_round_trip_uses_format_version_two(tmp_path: Path) -> None:
    store = SessionMetaStore(tmp_path)
    meta = SessionMeta.new("20260810-120000-abcd")
    store.save(meta)

    assert store.load() == meta
    assert json.loads((tmp_path / "meta.json").read_text())["format_version"] == 2


def test_meta_save_uses_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replaced: list[tuple[Path, Path]] = []

    monkeypatch.setattr(
        os,
        "replace",
        lambda source, target: replaced.append(
            (Path(source), Path(target))
        ),
    )
    SessionMetaStore(tmp_path).save(SessionMeta.new("session"))

    assert replaced and replaced[0][1] == tmp_path / "meta.json"


def test_missing_meta_returns_none(tmp_path: Path) -> None:
    assert SessionMetaStore(tmp_path).load() is None


def test_corrupt_meta_returns_none(tmp_path: Path) -> None:
    (tmp_path / "meta.json").write_text("{broken", encoding="utf-8")

    assert SessionMetaStore(tmp_path).load() is None


def test_old_format_meta_returns_none(tmp_path: Path) -> None:
    (tmp_path / "meta.json").write_text(
        json.dumps({"format_version": 1, "id": "old"}),
        encoding="utf-8",
    )

    assert SessionMetaStore(tmp_path).load() is None


def test_title_is_truncated_for_display() -> None:
    meta = SessionMeta.new("session")

    with_title = SessionMeta(
        format_version=2,
        id=meta.id,
        title="x" * 80,
        provider="",
        model="",
        message_count=0,
        total_tokens=0,
        created_at=meta.created_at,
        last_active=meta.last_active,
    )

    assert len(with_title.display_title()) <= 51


def test_timestamps_keep_timezone_awareness(tmp_path: Path) -> None:
    meta = SessionMeta.new("session")
    store = SessionMetaStore(tmp_path)
    store.save(meta)

    loaded = store.load()

    assert loaded is not None
    assert loaded.created_at.tzinfo is not None
    assert loaded.last_active.tzinfo is not None
    assert loaded.created_at == meta.created_at


def test_update_applies_changes_and_returns_meta(tmp_path: Path) -> None:
    store = SessionMetaStore(tmp_path)
    meta = SessionMeta.new("session")
    store.save(meta)

    updated = store.update(title="新标题", message_count=3)

    assert updated.title == "新标题"
    assert updated.message_count == 3
    assert store.load() == updated
