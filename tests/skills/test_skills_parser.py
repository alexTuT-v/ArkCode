from pathlib import Path

import pytest

from Arkcode.skills.parser import (
    SkillParseError,
    parse_frontmatter,
    parse_skill_file,
    substitute_arguments,
)


def write_skill(path: Path, frontmatter: str, body: str = "Do it") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return path


def test_parse_skill_defaults_and_absolute_source(tmp_path: Path) -> None:
    path = write_skill(
        tmp_path / "commit.md",
        "name: commit\ndescription: Commit code",
    )

    skill = parse_skill_file(path)

    assert skill.name == "commit"
    assert skill.description == "Commit code"
    assert skill.prompt_body == "Do it"
    assert skill.mode == "inline"
    assert skill.context == "full"
    assert skill.model is None
    assert skill.source_path == path.resolve()
    assert skill.is_directory is False


def test_parse_directory_skill_preserves_execution_fields(tmp_path: Path) -> None:
    path = write_skill(
        tmp_path / "review" / "SKILL.md",
        "\n".join(
            (
                "name: review",
                "description: Review code",
                "mode: fork",
                "model: claude-review",
                "context: recent",
            )
        ),
    )

    skill = parse_skill_file(path, is_directory=True)

    assert (skill.mode, skill.model, skill.context) == (
        "fork",
        "claude-review",
        "recent",
    )
    assert skill.is_directory is True


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("name: review", "opening"),
        ("---\nname: review", "closing"),
        ("---\nname: [\n---\nbody", "YAML"),
        ("---\n- name\n- review\n---\nbody", "mapping"),
    ],
)
def test_parse_frontmatter_rejects_invalid_documents(raw: str, message: str) -> None:
    with pytest.raises(SkillParseError, match=message):
        parse_frontmatter(raw)


@pytest.mark.parametrize(
    ("frontmatter", "message"),
    [
        ("description: Review code", "name"),
        ("name: review", "description"),
        ("name: ''\ndescription: Review code", "name"),
        ("name: review\ndescription: ''", "description"),
        ("name: Review\ndescription: Review code", "name"),
        ("name: review_it\ndescription: Review code", "name"),
        ("name: review\ndescription: Review code\nmode: background", "mode"),
        ("name: review\ndescription: Review code\ncontext: latest", "context"),
        ("name: review\ndescription: Review code\nmodel: 7", "model"),
    ],
)
def test_parse_skill_rejects_invalid_metadata(
    tmp_path: Path,
    frontmatter: str,
    message: str,
) -> None:
    path = write_skill(tmp_path / "invalid.md", frontmatter)

    with pytest.raises(SkillParseError, match=message):
        parse_skill_file(path)


def test_parse_skill_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SkillParseError, match="read"):
        parse_skill_file(tmp_path / "missing.md")


def test_substitute_arguments_replaces_every_occurrence() -> None:
    assert substitute_arguments("Review $ARGUMENTS, then test $ARGUMENTS", "src") == (
        "Review src, then test src"
    )


def test_substitute_without_placeholder_is_unchanged() -> None:
    assert substitute_arguments("Do it", "extra") == "Do it"
