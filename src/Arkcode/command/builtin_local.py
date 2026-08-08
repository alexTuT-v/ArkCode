"""纯本地查询命令。"""

from .command import Handler
from .registry import Registry
from .ui import UI


def make_help_handler(registry: Registry) -> Handler:
    async def handle_help(ui: UI, args: str) -> None:
        commands = registry.visible()
        width = max((len(command.name) for command in commands), default=0)
        ui.println(
            "\n".join(
                f"/{command.name.ljust(width)}  {command.description}"
                for command in commands
            )
        )

    return handle_help


async def handle_status(ui: UI, args: str) -> None:
    rows = (
        ("Mode:", str(ui.mode())),
        ("Tokens:", f"{ui.usage_in()} in / {ui.usage_out()} out"),
        ("Tools:", f"{ui.tool_count()} enabled"),
        ("Memories:", f"{len(ui.memory_files())} files"),
        ("Model:", ui.model_name()),
        ("Directory:", ui.cwd()),
    )
    width = max(len(key) for key, _ in rows)
    rendered = "\n".join(f"{key.ljust(width)} {value}" for key, value in rows)
    ui.println("ArkCode Status\n\n" + rendered)


async def handle_memory(ui: UI, args: str) -> None:
    files = ui.memory_files()
    ui.println("\n".join(files) if files else "无已加载的记忆文件")


async def handle_permission(ui: UI, args: str) -> None:
    ui.println(str(ui.mode()))


async def handle_session(ui: UI, args: str) -> None:
    ui.println(f"Session: {ui.session_id()}\nPath: {ui.session_path()}")
