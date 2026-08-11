from pathlib import Path

from Arkcode.commands import CommandRegistry, register_builtins
from Arkcode.context import new_session_context
from Arkcode.skills import SkillLoader
from Arkcode.tools import new_default_registry


def test_builtin_tool_contract_is_stable() -> None:
    registry = new_default_registry()
    definitions = registry.definitions()
    assert [item.name for item in definitions] == [
        "read_file",
        "write_file",
        "edit_file",
        "bash",
        "glob",
        "grep",
    ]
    assert [item.name for item in definitions if registry.is_read_only(item.name)] == [
        "read_file",
        "glob",
        "grep",
    ]


def test_builtin_slash_command_contract_is_stable() -> None:
    registry = CommandRegistry()
    register_builtins(registry)
    assert [item.name for item in registry.visible()] == [
        "clear",
        "compact",
        "do",
        "exit",
        "help",
        "mcp",
        "memory",
        "permission",
        "plan",
        "resume",
        "review",
        "sandbox",
            "session",
            "status",
            "team",
            "worktree",
        ]


def test_session_paths_are_stable(tmp_path: Path) -> None:
    context = new_session_context(str(tmp_path))

    assert Path(context.session_dir).parent == tmp_path / ".Arkcode" / "sessions"
    assert Path(context.spill_dir) == Path(context.session_dir) / "tool-results"


def test_project_skills_path_is_stable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "user-home")
    skill_path = tmp_path / ".Arkcode" / "skills" / "project-contract" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "---\nname: project-contract\n"
        "description: Project contract skill\n---\nUse it.",
        encoding="utf-8",
    )
    loader = SkillLoader(tmp_path)

    assert [skill.name for skill in loader.load_all()] == ["project-contract"]
    assert loader.get_source_label("project-contract") == "project"
