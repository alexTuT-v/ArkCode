from pathlib import Path

from Arkcode.instructions import Loader


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def test_loads_project_hidden_and_user_instructions_in_priority_order(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(project / "ArkCODE.md", "project")
    _write(project / ".Arkcode" / "ArkCODE.md", "hidden")
    _write(home / ".Arkcode" / "ArkCODE.md", "user")

    assert Loader(project, home).load() == "project\n\nhidden\n\nuser"


def test_expands_relative_include_and_only_matches_standalone_directive(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _write(project / "ArkCODE.md", "before\n@include docs/rules.md\nafter")
    _write(project / "docs" / "rules.md", "included")

    loaded = Loader(project, tmp_path / "home").load()

    assert loaded == "before\nincluded\nafter"


def test_reports_depth_cycle_escape_and_binary_includes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(
        project / "ArkCODE.md",
        "@include deep/1.md\n"
        "@include cycle/a.md\n"
        "@include ../outside.md\n"
        "@include binary.md",
    )
    for index in range(1, 7):
        following = f"@include {index + 1}.md" if index < 6 else "too deep"
        _write(project / "deep" / f"{index}.md", following)
    _write(project / "cycle" / "a.md", "@include b.md")
    _write(project / "cycle" / "b.md", "@include a.md")
    _write(tmp_path / "outside.md", "escaped")
    _write(project / "binary.md", b"abc\x00def")

    loaded = Loader(project, tmp_path / "home", max_depth=5).load()

    assert "超过最大 include 深度" in loaded
    assert "include 环路" in loaded
    assert "越出允许目录" in loaded
    assert "二进制文件" in loaded
    assert "escaped" not in loaded
    assert "abc" not in loaded


def test_missing_instruction_and_include_files_are_silently_skipped(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _write(project / "ArkCODE.md", "before\n@include missing.md\nafter")

    assert Loader(project, tmp_path / "missing-home").load() == "before\n\nafter"
