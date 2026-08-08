import pytest

from Arkcode.command import Kind, NopUI, Registry, register_builtins
from Arkcode.permission import Mode


class RecordingUI(NopUI):
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.errors: list[str] = []
        self.modes: list[Mode] = []
        self.injected: list[tuple[str, str]] = []
        self.compacts = 0
        self.busy = False

    def println(self, message: str) -> None:
        self.lines.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def set_mode(self, mode: Mode) -> None:
        self.modes.append(mode)

    def inject_and_send(self, label: str, prompt: str) -> None:
        self.injected.append((label, prompt))

    def force_compact(self) -> None:
        self.compacts += 1

    def idle(self) -> bool:
        return not self.busy

    def memory_files(self) -> list[str]:
        return ["MEMORY.md", "project_knowledge_api.md"]

    def session_id(self) -> str:
        return "20260808-120000-abcd"

    def session_path(self) -> str:
        return "/work/.Arkcode/sessions/id/conversation.jsonl"


def builtins() -> Registry:
    registry = Registry()
    register_builtins(registry)
    return registry


def test_registers_exactly_twelve_visible_commands() -> None:
    registry = builtins()
    assert [item.name for item in registry.visible()] == [
        "clear",
        "compact",
        "do",
        "exit",
        "help",
        "memory",
        "permission",
        "plan",
        "resume",
        "review",
        "session",
        "status",
    ]
    assert {item.kind for item in registry.visible()} == {
        Kind.LOCAL,
        Kind.UI,
        Kind.PROMPT,
    }


@pytest.mark.asyncio
async def test_help_and_status_render_from_ui_queries() -> None:
    registry = builtins()
    ui = RecordingUI()

    await registry.lookup("help").handler(ui, "ignored")  # type: ignore[union-attr]
    await registry.lookup("status").handler(ui, "ignored")  # type: ignore[union-attr]

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


@pytest.mark.asyncio
async def test_prompt_and_busy_ui_commands_follow_kind_contract() -> None:
    registry = builtins()
    ui = RecordingUI()
    await registry.lookup("do").handler(ui, "")  # type: ignore[union-attr]
    await registry.lookup("review").handler(ui, "")  # type: ignore[union-attr]
    ui.busy = True
    await registry.lookup("compact").handler(ui, "")  # type: ignore[union-attr]

    assert ui.modes == [Mode.DEFAULT]
    assert ui.injected[0][0] == "/do"
    assert "审查" in ui.injected[1][1]
    assert ui.compacts == 0
    assert ui.errors == ["请等待当前任务完成"]


@pytest.mark.asyncio
async def test_local_detail_commands_render_observable_values() -> None:
    registry = builtins()
    ui = RecordingUI()

    for name in ("memory", "permission", "session"):
        command = registry.lookup(name)
        assert command is not None
        await command.handler(ui, "ignored")

    assert ui.lines == [
        "MEMORY.md\nproject_knowledge_api.md",
        "default",
        "Session: 20260808-120000-abcd\n"
        "Path: /work/.Arkcode/sessions/id/conversation.jsonl",
    ]
