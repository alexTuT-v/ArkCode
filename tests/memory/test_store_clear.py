"""Store.clear 清空笔记并重建索引测试。"""

from pathlib import Path

from Arkcode.memory.store import Store


def test_clear_removes_notes_and_rebuilds_index(tmp_path: Path) -> None:
    store = Store(str(tmp_path))
    store.ensure_dir()
    (tmp_path / "user_preference_keep_memory.md").write_text(
        "---\ntype: user_preference\ntitle: t\n---\n内容",
        encoding="utf-8",
    )
    (tmp_path / "MEMORY.md").write_text(
        "- [user_preference] t — 内容",
        encoding="utf-8",
    )

    store.clear()

    assert not (tmp_path / "user_preference_keep_memory.md").exists()
    assert (tmp_path / "MEMORY.md").exists()
    assert "- [user_preference]" not in (tmp_path / "MEMORY.md").read_text(
        encoding="utf-8"
    )
