import logging
from pathlib import Path

from Arkcode.skills.loader import SkillLoader


def write_skill(
    root: Path,
    relative: str,
    name: str,
    description: str,
    body: str = "SOP",
) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}",
        encoding="utf-8",
    )
    return path


def make_loader(tmp_path: Path, monkeypatch) -> tuple[SkillLoader, Path, Path]:
    project = tmp_path / "project"
    user_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: user_home)
    return (
        SkillLoader(project),
        project / ".Arkcode" / "skills",
        user_home / ".Arkcode" / "skills",
    )


def test_loads_single_file_and_directory_skills(tmp_path: Path, monkeypatch) -> None:
    loader, project_skills, _ = make_loader(tmp_path, monkeypatch)
    write_skill(project_skills, "commit.md", "commit", "Commit")
    directory = write_skill(
        project_skills,
        "review/SKILL.md",
        "review",
        "Review",
    )
    (directory.parent / "references.py").write_text("VALUE = 1", encoding="utf-8")

    loaded = loader.load_all()

    assert [skill.name for skill in loaded] == ["commit", "review"]
    assert loader.get("commit").is_directory is False  # type: ignore[union-attr]
    assert loader.get("review").is_directory is True  # type: ignore[union-attr]


def test_loads_user_skills_and_reports_sources(tmp_path: Path, monkeypatch) -> None:
    loader, project_skills, user_skills = make_loader(tmp_path, monkeypatch)
    write_skill(project_skills, "project.md", "project", "Project")
    write_skill(user_skills, "user/SKILL.md", "user", "User")
    write_skill(user_skills, "personal.md", "personal", "Personal")

    loader.load_all()

    assert loader.get_source_label("project") == "project"
    assert loader.get_source_label("user") == "user"
    assert loader.get_source_label("personal") == "user"
    assert loader.get_source_label("missing") is None


def test_project_skill_overrides_user_skill(tmp_path: Path, monkeypatch) -> None:
    loader, project_skills, user_skills = make_loader(tmp_path, monkeypatch)
    write_skill(project_skills, "review.md", "review", "project")
    write_skill(user_skills, "review.md", "review", "user")

    loader.load_all()

    skill = loader.get("review")
    assert skill is not None
    assert skill.description == "project"
    assert loader.get_source_label("review") == "project"


def test_catalog_is_sorted_and_excludes_prompt_body(
    tmp_path: Path,
    monkeypatch,
) -> None:
    loader, project_skills, _ = make_loader(tmp_path, monkeypatch)
    write_skill(project_skills, "z.md", "zeta", "Z", "secret z")
    write_skill(project_skills, "a.md", "alpha", "A", "secret a")

    loader.load_all()

    assert loader.get_catalog() == [("alpha", "A"), ("zeta", "Z")]


def test_bad_skill_warns_without_blocking_others(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    loader, project_skills, _ = make_loader(tmp_path, monkeypatch)
    project_skills.mkdir(parents=True)
    (project_skills / "bad.md").write_text("not frontmatter", encoding="utf-8")
    write_skill(project_skills, "good.md", "good", "Good")

    with caplog.at_level(logging.WARNING):
        loaded = loader.load_all()

    assert [skill.name for skill in loaded] == ["good"]
    assert "bad.md" in caplog.text


def test_get_hot_reloads_changed_body(tmp_path: Path, monkeypatch) -> None:
    loader, project_skills, _ = make_loader(tmp_path, monkeypatch)
    path = write_skill(project_skills, "review.md", "review", "Review", "v1")
    loader.load_all()
    path.write_text(
        "---\nname: review\ndescription: Review\n---\nv2",
        encoding="utf-8",
    )

    skill = loader.get("review")

    assert skill is not None
    assert skill.prompt_body == "v2"


def test_get_falls_back_to_cache_when_hot_reload_fails(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    loader, project_skills, _ = make_loader(tmp_path, monkeypatch)
    path = write_skill(project_skills, "review.md", "review", "Review", "v1")
    loader.load_all()
    path.write_text("broken", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        skill = loader.get("review")

    assert skill is not None
    assert skill.prompt_body == "v1"
    assert "review" in caplog.text


def test_reload_discovers_additions_and_removals(tmp_path: Path, monkeypatch) -> None:
    loader, project_skills, _ = make_loader(tmp_path, monkeypatch)
    old = write_skill(project_skills, "old.md", "old", "Old")
    loader.load_all()
    old.unlink()
    write_skill(project_skills, "new.md", "new", "New")

    loaded = loader.reload()

    assert [skill.name for skill in loaded] == ["new"]
    assert loader.get("old") is None


def test_missing_directories_are_empty(tmp_path: Path, monkeypatch) -> None:
    loader, _, _ = make_loader(tmp_path, monkeypatch)

    assert loader.load_all() == []
    assert loader.get_catalog() == []
    assert loader.get("missing") is None
