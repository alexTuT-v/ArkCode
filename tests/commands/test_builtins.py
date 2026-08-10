"""内置命令的名称、种类与渲染行为测试。"""

import pytest

from Arkcode.commands import CommandKind, CommandRegistry, register_builtins
from Arkcode.commands.dispatcher import dispatch
from Arkcode.permissions import Mode

from .fakes import make_context


def builtins() -> CommandRegistry:
    registry = CommandRegistry()
    register_builtins(registry)
    return registry


def test_registers_exactly_fourteen_visible_commands() -> None:
    registry = builtins()
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
    ]
    assert {item.kind for item in registry.visible()} == {
        CommandKind.LOCAL,
        CommandKind.UI,
        CommandKind.PROMPT,
    }


@pytest.mark.asyncio
async def test_help_and_status_render_from_ports() -> None:
    registry = builtins()
    context, ui, _, _, status = make_context()
    status.memory = ["MEMORY.md", "project_knowledge_api.md"]
    status.session_id_value = "20260808-120000-abcd"
    status.session_path_value = "/work/.Arkcode/sessions/id/conversation.jsonl"
    status.usage_in = 120
    status.usage_out = 34

    await dispatch(registry, "help", context)
    await dispatch(registry, "status", context)

    assert (
        sum(
            f"/{name}" in ui.lines[0]
            for name in (
                "help",
                "status",
                "memory",
                "permission",
                "session",
                "clear",
                "review",
                "exit",
                "plan",
                "do",
                "compact",
                "resume",
            )
        )
        == 12
    )
    assert all(
        key in ui.lines[1]
        for key in (
            "Mode:",
            "Tokens:",
            "Tools:",
            "Memories:",
            "Model:",
            "Directory:",
        )
    )
    assert "120 in / 34 out" in ui.lines[1]


@pytest.mark.asyncio
async def test_prompt_and_busy_ui_commands_follow_kind_contract() -> None:
    registry = builtins()
    context, ui, session, _, _ = make_context()

    await dispatch(registry, "do", context)
    await dispatch(registry, "review", context)
    session.busy = True
    await dispatch(registry, "compact", context)

    assert session.modes == [Mode.DEFAULT]
    assert session.submitted[0][0] == "/do"
    assert "审查" in session.submitted[1][1]
    assert session.compacts == 0
    assert ui.errors == ["请等待当前任务完成"]


@pytest.mark.asyncio
async def test_local_detail_commands_render_observable_values() -> None:
    registry = builtins()
    context, ui, _, _, status = make_context()
    status.memory = ["MEMORY.md", "project_knowledge_api.md"]
    status.session_id_value = "20260808-120000-abcd"
    status.session_path_value = "/work/.Arkcode/sessions/id/conversation.jsonl"

    for name in ("memory", "permission", "session"):
        await dispatch(registry, name, context)

    assert ui.lines == [
        "MEMORY.md\nproject_knowledge_api.md",
        "default",
        "Session: 20260808-120000-abcd\n"
        "Path: /work/.Arkcode/sessions/id/conversation.jsonl",
    ]


@pytest.mark.asyncio
async def test_help_with_command_name_shows_detail() -> None:
    registry = builtins()
    context, ui, _, _, _ = make_context(args="session")

    await dispatch(registry, "help", context)

    output = ui.lines[0]
    assert "/session" in output
    assert "用法: /session [list | resume <id> | new | delete <id>]" in output


@pytest.mark.asyncio
async def test_help_unknown_command_is_friendly() -> None:
    registry = builtins()
    context, ui, _, _, _ = make_context(args="nope")

    await dispatch(registry, "help", context)

    assert "未知命令：nope" in ui.lines[0]
