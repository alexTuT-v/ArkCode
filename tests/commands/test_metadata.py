"""Command 元数据（usage / arg_prompt）测试。"""

from Arkcode.commands import Command, CommandContext, CommandKind


async def _noop(context: CommandContext) -> None:
    return None


def test_command_carries_usage_metadata() -> None:
    command = Command(
        "session",
        "显示当前会话信息",
        CommandKind.LOCAL,
        _noop,
        usage="/session [list | resume <id> | new | delete <id>]",
        arg_prompt="子命令与参数",
    )

    assert command.usage == "/session [list | resume <id> | new | delete <id>]"
    assert command.arg_prompt == "子命令与参数"


def test_usage_defaults_to_empty() -> None:
    command = Command("status", "状态", CommandKind.LOCAL, _noop)

    assert command.usage == ""
    assert command.arg_prompt == ""
