"""Skill 管理命令与动态 Skill 命令注册测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from Arkcode.commands import (
    CommandContext,
    CommandRegistry,
    register_builtins,
    register_skill_commands,
    register_skill_management,
)
from Arkcode.commands.dispatcher import dispatch
from Arkcode.skills import SkillLoader

from .fakes import FakeSession, FakeSkills, FakeStatus, FakeUI


def write_skill(
    root: Path,
    name: str,
    *,
    mode: str = "inline",
    body: str = "Run $ARGUMENTS",
) -> Path:
    path = root / ".Arkcode" / "skills" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {name} description\n"
        f"mode: {mode}\n---\n{body}",
        encoding="utf-8",
    )
    return path


class RecordingExecutor:
    pass


def loaded_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *names: tuple[str, str],
) -> SkillLoader:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for name, mode in names:
        write_skill(tmp_path, name, mode=mode)
    loader = SkillLoader(tmp_path)
    loader.load_all()
    return loader


@pytest.mark.asyncio
async def test_skill_management_list_info_reload_and_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = loaded_loader(tmp_path, monkeypatch)
    registry = CommandRegistry()
    register_skill_management(registry, loader)

    ui = FakeUI()
    session = FakeSession()
    skills = FakeSkills()
    skills.skills = [
        ("alpha", "Alpha description", "project"),
        ("beta", "Beta description", "user"),
    ]
    skills.info = "name: alpha\npath: /work/alpha.md\ndirectory: false"
    skills.info_for = "alpha"
    status = FakeStatus()

    for args in ("", "list", "info alpha", "info missing", "reload", "wat"):
        context = CommandContext(
            args=args,
            session=session,
            skills=skills,
            status=status,
            ui=ui,
            sandbox=session,
        )
        await dispatch(registry, "skill", context)

    assert "alpha" in ui.lines[0] and "project" in ui.lines[0]
    assert "/work/alpha.md" in ui.lines[2]
    assert skills.reload_count == 1
    assert any("missing" in error for error in ui.errors)
    assert any("Usage:" in error for error in ui.errors)


@pytest.mark.asyncio
async def test_dynamic_skill_command_delegates_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = loaded_loader(tmp_path, monkeypatch, ("commit", "inline"))
    registry = CommandRegistry()
    register_skill_commands(registry, loader, RecordingExecutor())  # type: ignore[arg-type]
    ui = FakeUI()
    skills = FakeSkills()

    context = CommandContext(
        args="src",
        session=FakeSession(),
        skills=skills,
        status=FakeStatus(),
        ui=ui,
        sandbox=FakeSession(),
    )
    await dispatch(registry, "commit", context)

    command = registry.lookup("commit")
    assert command is not None
    assert command.description.endswith("[skill]")
    assert skills.invoked == [("commit", "src")]


def test_skill_command_can_override_builtin_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = loaded_loader(tmp_path, monkeypatch, ("review", "inline"))
    registry = CommandRegistry()
    register_builtins(registry)

    register_skill_commands(
        registry,
        loader,
        RecordingExecutor(),  # type: ignore[arg-type]
    )

    command = registry.lookup("review")
    assert command is not None
    assert command.description == "review description [skill]"
    assert sum(item.name == "review" for item in registry.visible()) == 1
