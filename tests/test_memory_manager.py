from pathlib import Path

from Arkcode.memory import Manager


def test_list_files_sorts_markdown_files_at_both_levels(tmp_path: Path) -> None:
    project = tmp_path / "project"
    user = tmp_path / "user"
    project.mkdir()
    user.mkdir()
    for path in (project / "z.md", project / "MEMORY.md", user / "a.md"):
        path.write_text("note", encoding="utf-8")
    (project / "ignore.txt").write_text("no", encoding="utf-8")

    manager = Manager(str(project), str(user), None, "")

    assert manager.list_files() == (["MEMORY.md", "z.md"], ["a.md"])
