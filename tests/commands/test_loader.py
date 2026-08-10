"""自定义 Markdown 命令加载器测试。"""

import asyncio
from pathlib import Path

from Arkcode.commands import CommandContext, CommandKind, CommandRegistry
from Arkcode.commands.loader import register_custom_commands

from .fakes import FakeSession, FakeSkills, FakeStatus, FakeUI


def write_command(
    root: Path,
    relative: str,
    body: str,
    frontmatter: str = "",
) -> Path:
    path = root / ".Arkcode" / "commands" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    text = f"---\n{frontmatter}\n---\n{body}" if frontmatter else body
    path.write_text(text, encoding="utf-8")
    return path


def test_loader_registers_prompt_commands_with_namespace(tmp_path: Path) -> None:
    write_command(
        tmp_path,
        "git/log.md",
        "总结最近的提交: $ARGUMENTS",
        "description: 查看 git 日志",
    )
    registry = CommandRegistry()

    register_custom_commands(registry, tmp_path)

    command = registry.lookup("git:log")
    assert command is not None
    assert command.kind is CommandKind.PROMPT
    assert command.description == "查看 git 日志"


def test_loader_substitutes_arguments(tmp_path: Path) -> None:
    write_command(tmp_path, "run.md", "执行 $ARGUMENTS")
    registry = CommandRegistry()
    register_custom_commands(registry, tmp_path)

    async def invoke() -> FakeSession:
        command = registry.lookup("run")
        assert command is not None
        session = FakeSession()
        context = CommandContext(
            args="tests",
            session=session,
            skills=FakeSkills(),
            status=FakeStatus(),
            ui=FakeUI(),
            sandbox=FakeSession(),
        )
        await command.handler(context)
        return session

    session = asyncio.run(invoke())
    assert session.submitted == [("/run", "执行 tests")]


def test_loader_appends_user_request_without_placeholder(tmp_path: Path) -> None:
    write_command(tmp_path, "review.md", "请审查代码。")
    registry = CommandRegistry()
    register_custom_commands(registry, tmp_path)

    async def invoke() -> FakeSession:
        command = registry.lookup("review")
        assert command is not None
        session = FakeSession()
        context = CommandContext(
            args="main.py",
            session=session,
            skills=FakeSkills(),
            status=FakeStatus(),
            ui=FakeUI(),
            sandbox=FakeSession(),
        )
        await command.handler(context)
        return session

    session = asyncio.run(invoke())
    assert session.submitted[0][0] == "/review"
    assert "## User Request\nmain.py" in session.submitted[0][1]


def test_loader_registers_aliases_and_skips_builtin_conflicts(
    tmp_path: Path,
) -> None:
    write_command(
        tmp_path,
        "gl.md",
        "查看日志 $ARGUMENTS",
        "aliases: [glog]\n",
    )
    write_command(tmp_path, "help.md", "覆盖内置")
    registry = CommandRegistry()
    from Arkcode.commands import register_builtins

    register_builtins(registry)

    register_custom_commands(registry, tmp_path)

    assert registry.lookup("gl").aliases == ["glog"]
    assert registry.lookup("help").description == "显示全部可用命令"
