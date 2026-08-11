"""系统提示模块、环境段和补充提醒的行为测试。"""

from pathlib import Path

import pytest
from rich.console import Console

from Arkcode.prompts import (
    EXECUTE_DIRECTIVE,
    Environment,
    Module,
    assemble_system,
    build_system_prompt,
    combine_reminders,
    deferred_tools_reminder,
    fixed_modules,
    gather_environment,
    optional_modules,
    plan_reminder,
)
from Arkcode.tui.views.banner import render_banner


def rendered_text(renderable: object) -> str:
    console = Console(width=80, record=True)
    console.print(renderable)
    return console.export_text()


def test_banner_uses_compact_ark_code_pixel_logo() -> None:
    text = rendered_text(render_banner("0.1.0", "/work/project"))
    logo_lines = text.splitlines()[:5]

    assert len(logo_lines) == 5
    assert all(len(line) <= 80 for line in logo_lines)
    assert all("█" in line for line in logo_lines)
    assert "Ark Code v0.1.0" in text
    assert "/help" in text


def test_system_prompt_is_ordered_deterministic_and_reinforces_tools() -> None:
    first = build_system_prompt()

    assert first == build_system_prompt()
    assert first.index("Identity") < first.index("Tool use")
    assert "\n\n" in first
    assert "read_file" in first
    assert "before editing" in first.lower()
    assert len(fixed_modules()) == 7
    assert [module.priority for module in fixed_modules()] == list(range(10, 80, 10))
    assert [module.content for module in optional_modules()] == ["", "", ""]


def test_system_prompt_injects_instructions_and_memory_in_priority_order() -> None:
    prompt = build_system_prompt("project rules", "remembered facts")

    assert prompt.index("project rules") < prompt.index("remembered facts")
    assert build_system_prompt("", "") == build_system_prompt()


def test_assemble_system_sorts_extensions_and_skips_empty_slots() -> None:
    result = assemble_system(
        [
            Module("late", 30, "third"),
            Module("empty", 20, ""),
            Module("first", 10, "first"),
            Module("middle", 20, "second"),
        ]
    )

    assert result == "first\n\nsecond\n\nthird"


def test_environment_renders_only_available_fields() -> None:
    environment = Environment(
        working_dir="/workspace",
        platform="darwin",
        date="2026-07-31",
        git_status="2 files changed",
        version="0.5.0",
        model="test-model",
    )

    rendered = environment.render()

    assert "Environment" in rendered
    assert "Working directory: /workspace" in rendered
    assert "Platform: darwin" in rendered
    assert "Git status: 2 files changed" in rendered
    assert "API" not in rendered


def test_environment_changes_do_not_change_stable_prompt() -> None:
    stable = build_system_prompt()
    first = Environment("/one", "darwin", "2026-01-01", "clean", "1", "m1")
    second = Environment("/two", "linux", "2027-02-02", "changed", "2", "m2")

    assert first.render() != second.render()
    assert build_system_prompt() == stable
    assert "/one" not in stable
    assert "2026-01-01" not in stable
    assert "clean" not in stable


def test_gather_environment_degrades_outside_git_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    environment = gather_environment("0.5.0", "test-model")
    rendered = environment.render()

    assert environment.working_dir == str(tmp_path)
    assert environment.git_status == ""
    assert "Working directory" in rendered
    assert "Platform" in rendered
    assert "Date" in rendered
    assert "Version: 0.5.0" in rendered
    assert "Model: test-model" in rendered
    assert "Git status" not in rendered


def test_plan_reminders_are_tagged_and_vary_by_detail() -> None:
    full = plan_reminder(full=True)
    concise = plan_reminder(full=False)

    assert full.startswith("<system-reminder>")
    assert full.endswith("</system-reminder>")
    assert len(full) > len(concise)
    assert "/do" in full
    assert EXECUTE_DIRECTIVE == "请按上面的计划开始执行。"


def test_deferred_tools_reminder_lists_names_only() -> None:
    names = ["mcp__demo__search", "mcp__demo__fetch"]

    reminder = deferred_tools_reminder(names)

    assert reminder.startswith("<system-reminder>")
    assert reminder.endswith("</system-reminder>")
    assert "ToolSearch" in reminder
    assert 'select:<name>[,<name>...]' in reminder
    assert "\n".join(names) in reminder
    assert "input_schema" not in reminder
    assert names == ["mcp__demo__search", "mcp__demo__fetch"]


def test_deferred_tools_reminder_omits_empty_catalog() -> None:
    assert deferred_tools_reminder([]) == ""


def test_combine_reminders_filters_empty_values_without_nesting() -> None:
    plan = plan_reminder(full=True)
    deferred = deferred_tools_reminder(["mcp__demo__search"])

    combined = combine_reminders("", plan, deferred)

    assert combined == f"{plan}\n\n{deferred}"
    assert combined.count("<system-reminder>") == 2
