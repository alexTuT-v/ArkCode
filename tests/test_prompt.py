from rich.console import Console

from Arkcode.prompt import (
    EXECUTE_DIRECTIVE,
    PLAN_MODE_REMINDER,
    SYSTEM_PROMPT,
    render_banner,
)


def rendered_text(renderable: object) -> str:
    console = Console(width=80, record=True)
    console.print(renderable)
    return console.export_text()


def test_banner_uses_compact_ark_code_pixel_logo() -> None:
    banner = render_banner("0.1.0", "/work/project")
    text = rendered_text(banner)
    logo_lines = text.splitlines()[:5]

    assert len(logo_lines) == 5
    assert all(len(line) <= 80 for line in logo_lines)
    assert all("█" in line for line in logo_lines)
    assert any("▓" in line for line in logo_lines)
    assert "/\\_/\\" not in text
    assert "( o.o )" not in text
    assert "> ^ <" not in text
    assert "Ark Code v0.1.0" in text
    assert "/work/project" in text
    assert "Ready" in text


def test_banner_renders_bright_cyan_body_and_dark_cyan_shadow() -> None:
    console = Console(
        width=80,
        record=True,
        force_terminal=True,
        color_system="truecolor",
    )

    console.print(render_banner("0.1.0", "/work/project"))
    styled = console.export_text(styles=True)

    assert "\x1b[1;38;2;0;255;255m" in styled
    assert "\x1b[38;2;0;139;139m" in styled


def test_plan_mode_messages_define_read_only_planning_then_execution() -> None:
    assert "read_file" in PLAN_MODE_REMINDER
    assert "write" in PLAN_MODE_REMINDER.lower()
    assert "/do" in PLAN_MODE_REMINDER
    assert EXECUTE_DIRECTIVE == "请按上面的计划开始执行。"


def test_system_prompt_describes_multi_step_agent_loop() -> None:
    normalized = " ".join(SYSTEM_PROMPT.split())
    assert "Keep using tools across multiple steps" in normalized
    assert "only give your final concise answer once the task is complete" in (
        normalized
    )
