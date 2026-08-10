"""Slash 命令补全状态机单元测试。"""

from Arkcode.commands import Command, CommandContext, CommandKind, CommandRegistry
from Arkcode.tui.widgets.completion import MAX_ROWS, CompletionMenu


async def _noop(context: CommandContext) -> None:
    return None


def registry() -> CommandRegistry:
    result = CommandRegistry()
    for name in ("status", "session", "help", "resume", "review", "secret"):
        result.register(
            Command(
                name,
                f"{name} command",
                CommandKind.LOCAL,
                _noop,
                hidden=name == "secret",
            )
        )
    return result


def test_completion_filters_primary_names_and_handles_zero_matches() -> None:
    menu = CompletionMenu()
    menu.update("/s", registry())
    assert menu.active is True
    assert [item.name for item in menu.items] == ["session", "status"]

    menu.update("/unknown", registry())
    assert menu.active is True
    assert menu.selected() is None
    assert "无匹配" in menu.render(80).plain


def test_completion_navigation_scrolls_and_hide_resets() -> None:
    commands = CommandRegistry()
    for index in range(MAX_ROWS + 2):
        commands.register(
            Command(f"cmd{index}", "description", CommandKind.LOCAL, _noop)
        )
    menu = CompletionMenu()
    menu.update("/", commands)

    for _ in range(MAX_ROWS + 1):
        menu.move_down()

    assert menu.cursor == MAX_ROWS + 1
    assert menu.offset > 0
    assert "↑" in menu.render(80).plain
    menu.hide()
    assert menu.active is False
    assert menu.items == []


def test_completion_disables_for_plain_or_multiline_input() -> None:
    menu = CompletionMenu()
    menu.update("/", registry())
    menu.update("/status\nextra", registry())
    assert menu.active is False

    menu.update("hello", registry())
    assert menu.active is False

    menu.update(" /status", registry())
    assert menu.active is False
