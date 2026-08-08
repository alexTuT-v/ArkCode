import asyncio
from pathlib import Path

import pytest

from Arkcode.command import (
    NopUI,
    Registry,
    register_builtins,
    register_skill_commands,
    register_skill_management,
)
from Arkcode.skills import SkillLoader, SkillMeta


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
    def __init__(self) -> None:
        self.inline: list[tuple[SkillMeta, str]] = []
        self.fork: list[tuple[SkillMeta, str]] = []
        self.fork_result = "fork result"
        self.fork_error: Exception | None = None

    def execute_inline(self, skill: SkillMeta, args: str) -> None:
        self.inline.append((skill, args))

    async def execute_fork(self, skill: SkillMeta, args: str) -> str:
        self.fork.append((skill, args))
        if self.fork_error is not None:
            raise self.fork_error
        return self.fork_result


class RecordingUI(NopUI):
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.errors: list[str] = []
        self.injected: list[tuple[str, str]] = []
        self.system_messages: list[tuple[str, str]] = []
        self.tasks: list[asyncio.Task[None]] = []
        self.reload_count = 0
        self.skills = [
            ("alpha", "Alpha description", "project"),
            ("beta", "Beta description", "user"),
        ]
        self.info = "name: alpha\npath: /work/alpha.md\ndirectory: false"

    def println(self, message: str) -> None:
        self.lines.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def inject_and_send(self, label: str, prompt: str) -> None:
        self.injected.append((label, prompt))

    def skill_list(self) -> list[tuple[str, str, str]]:
        return self.skills

    def skill_info(self, name: str) -> str | None:
        return self.info if name == "alpha" else None

    def reload_skills(self) -> None:
        self.reload_count += 1

    def append_system_message(self, name: str, result: str) -> None:
        self.system_messages.append((name, result))

    def track_skill_task(self, task: asyncio.Task[None]) -> None:
        self.tasks.append(task)


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
    registry = Registry()
    register_skill_management(registry, loader)
    command = registry.lookup("skill")
    assert command is not None
    ui = RecordingUI()

    for args in ("", "list", "info alpha", "info missing", "reload", "wat"):
        await command.handler(ui, args)

    assert "alpha" in ui.lines[0] and "project" in ui.lines[0]
    assert "/work/alpha.md" in ui.lines[2]
    assert ui.reload_count == 1
    assert any("missing" in error for error in ui.errors)
    assert any("Usage:" in error for error in ui.errors)


@pytest.mark.asyncio
async def test_inline_skill_hot_reloads_then_triggers_main_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = loaded_loader(tmp_path, monkeypatch, ("commit", "inline"))
    executor = RecordingExecutor()
    registry = Registry()
    register_skill_commands(registry, loader, executor)  # type: ignore[arg-type]
    write_skill(tmp_path, "commit", body="Updated $ARGUMENTS")
    ui = RecordingUI()

    command = registry.lookup("commit")
    assert command is not None
    await command.handler(ui, "src")

    assert command.description.endswith("[skill]")
    assert executor.inline[0][0].prompt_body == "Updated $ARGUMENTS"
    assert executor.inline[0][1] == "src"
    assert ui.injected == [("/commit", "/commit src")]


def test_skill_command_can_override_builtin_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = loaded_loader(tmp_path, monkeypatch, ("review", "inline"))
    registry = Registry()
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


@pytest.mark.asyncio
async def test_fork_skill_runs_in_tracked_background_task_and_flows_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = loaded_loader(tmp_path, monkeypatch, ("research", "fork"))
    executor = RecordingExecutor()
    registry = Registry()
    register_skill_commands(registry, loader, executor)  # type: ignore[arg-type]
    ui = RecordingUI()

    command = registry.lookup("research")
    assert command is not None
    await command.handler(ui, "topic")
    await asyncio.gather(*ui.tasks)

    assert executor.fork[0][1] == "topic"
    assert ui.injected == []
    assert ui.system_messages == [("research", "fork result")]


@pytest.mark.asyncio
async def test_fork_handler_converts_unexpected_errors_before_flow_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = loaded_loader(tmp_path, monkeypatch, ("research", "fork"))
    executor = RecordingExecutor()
    executor.fork_error = RuntimeError("boom")
    registry = Registry()
    register_skill_commands(registry, loader, executor)  # type: ignore[arg-type]
    ui = RecordingUI()

    await registry.lookup("research").handler(ui, "")  # type: ignore[union-attr]
    await asyncio.gather(*ui.tasks)

    assert ui.system_messages == [("research", "[skill research failed: boom]")]
