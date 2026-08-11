from pathlib import Path

import pytest

from Arkcode.memory import Manager, Store, UpdateAction


def test_store_create_update_delete_note(tmp_path: Path) -> None:
    store = Store(str(tmp_path / "memory"))
    create = UpdateAction(
        action="create",
        level="project",
        type="project_knowledge",
        title="API 约定",
        slug="api_conventions",
        content="所有 API 返回统一 envelope。",
    )

    store.apply([create])

    note = tmp_path / "memory" / "project_knowledge_api_conventions.md"
    assert note.is_file()
    assert "type: project_knowledge" in note.read_text()
    assert "[project_knowledge] API 约定" in store.load_index()

    store.apply(
        [
            UpdateAction(
                action="update",
                level="project",
                filename=note.name,
                title="API 响应约定",
                content="API 返回 data/error envelope。",
            )
        ]
    )
    updated = note.read_text()
    assert "API 响应约定" in updated
    assert "API 返回 data/error envelope" in updated
    assert "created:" in updated and "updated:" in updated
    assert "API 响应约定" in store.load_index()

    store.apply([UpdateAction(action="delete", level="project", filename=note.name)])
    assert not note.exists()
    assert "API 响应约定" not in store.load_index()


def test_store_same_name_create_updates_and_preserves_created(
    tmp_path: Path,
) -> None:
    store = Store(str(tmp_path / "memory"))
    first = UpdateAction(
        action="create",
        level="user",
        type="user_preference",
        title="语言",
        slug="language",
        content="中文。",
    )
    store.apply([first])
    path = tmp_path / "memory" / "user_preference_language.md"
    created = Store._parse_note(path)[0]["created"]

    store.apply(
        [
            UpdateAction(
                action="create",
                level="user",
                type="user_preference",
                title="语言偏好",
                slug="language",
                content="简体中文。",
            )
        ]
    )

    metadata, content = Store._parse_note(path)
    assert metadata["created"] == created
    assert metadata["title"] == "语言偏好"
    assert content == "简体中文。"


def test_store_rejects_filename_escape(tmp_path: Path) -> None:
    store = Store(str(tmp_path / "memory"))

    with pytest.raises(ValueError):
        store.apply(
            [UpdateAction(action="delete", level="project", filename="../secret.md")]
        )


def test_store_read_rejects_path_escape(tmp_path: Path) -> None:
    store = Store(str(tmp_path / "memory"))

    with pytest.raises(ValueError, match="非法记忆文件名"):
        store.read("../secret.md")


def test_store_lists_structured_entries_and_reads_valid_file(
    tmp_path: Path,
) -> None:
    from Arkcode.memory import MemoryScope

    store = Store(str(tmp_path / "memory"))
    store.apply(
        [
            UpdateAction(
                action="create",
                level="user",
                type="user_preference",
                title="回答语言",
                slug="response_language",
                content="用户偏好中文回答。",
            )
        ]
    )

    entries = store.list_entries(MemoryScope.USER)

    assert len(entries) == 1
    assert entries[0].key == "user:user_preference_response_language.md"
    assert entries[0].preview == "用户偏好中文回答。"
    assert entries[0].updated_at
    assert "用户偏好中文回答" in store.read(entries[0].filename)


def test_manager_load_index_merges_project_first_and_truncates(tmp_path: Path) -> None:
    project = tmp_path / "project"
    user = tmp_path / "user"
    project.mkdir()
    user.mkdir()
    (project / "MEMORY.md").write_text("project index", encoding="utf-8")
    (user / "MEMORY.md").write_text("user index", encoding="utf-8")
    manager = Manager(str(project), str(user), None, "")

    assert manager.load_index() == "project index\n\nuser index"

    (project / "MEMORY.md").write_text("知" * 30_000, encoding="utf-8")
    truncated = manager.load_index()
    assert truncated.endswith("(index truncated)")
    assert len(truncated.encode("utf-8")) <= 25 * 1024
