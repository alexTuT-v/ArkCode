"""ExecutionPathContext 与六个核心工具显式 cwd 测试。"""

import asyncio
from pathlib import Path

import pytest

from Arkcode.tools.builtins.bash import BashTool
from Arkcode.tools.builtins.edit_file import EditFileTool
from Arkcode.tools.builtins.glob import GlobTool
from Arkcode.tools.builtins.grep import GrepTool
from Arkcode.tools.builtins.read_file import ReadFileTool
from Arkcode.tools.builtins.write_file import WriteFileTool
from Arkcode.tools.workspace import (
    Access,
    ExecutionPathContext,
    PathPermissionError,
    current_workspace,
    resolve_path,
    workspace_scope,
)


def test_default_workspace_is_process_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    context = current_workspace()
    assert context.cwd == tmp_path.resolve()
    assert context.workspace_root == tmp_path.resolve()


def test_workspace_scope_nesting_restores(tmp_path: Path) -> None:
    outer = ExecutionPathContext.at(tmp_path)
    inner = ExecutionPathContext.at(tmp_path / "inner")
    with workspace_scope(outer):
        assert current_workspace() == outer
        with workspace_scope(inner):
            assert current_workspace() == inner
        assert current_workspace() == outer


def test_workspace_scope_isolated_between_tasks(tmp_path: Path) -> None:
    first = ExecutionPathContext.at(tmp_path / "a")
    second = ExecutionPathContext.at(tmp_path / "b")

    async def probe(context: ExecutionPathContext) -> Path:
        with workspace_scope(context):
            await asyncio.sleep(0.01)
            return current_workspace().cwd

    async def run() -> None:
        results = await asyncio.gather(
            probe(first),
            probe(second),
            probe(first),
        )
        assert results == [
            (tmp_path / "a").resolve(),
            (tmp_path / "b").resolve(),
            (tmp_path / "a").resolve(),
        ]

    asyncio.run(run())


def test_resolve_path_relative_and_absolute(tmp_path: Path) -> None:
    with workspace_scope(ExecutionPathContext.at(tmp_path)):
        assert resolve_path("a.txt", Access.READ) == (tmp_path / "a.txt").resolve()
        assert resolve_path(str(tmp_path / "b.txt"), Access.WRITE) == (
            tmp_path / "b.txt"
        ).resolve()


def test_resolve_path_rejects_parent_and_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with workspace_scope(ExecutionPathContext.at(tmp_path)):
        with pytest.raises(PathPermissionError):
            resolve_path("../outside.txt", Access.READ)
        link = tmp_path / "escape"
        link.symlink_to(outside)
        with pytest.raises(PathPermissionError):
            resolve_path("escape", Access.READ)


def test_readonly_shared_target_allows_read_but_not_write(tmp_path: Path) -> None:
    shared = tmp_path.parent / "shared"
    shared.mkdir(exist_ok=True)
    (shared / "dep.txt").write_text("dep", encoding="utf-8")
    context = ExecutionPathContext(
        cwd=tmp_path,
        workspace_root=tmp_path,
        readonly_shared_targets=(shared,),
    )
    with workspace_scope(context):
        assert resolve_path(str(shared / "dep.txt"), Access.READ) == (
            shared / "dep.txt"
        ).resolve()
        with pytest.raises(PathPermissionError):
            resolve_path(str(shared / "new.txt"), Access.WRITE)


@pytest.mark.asyncio
async def test_file_tools_resolve_relative_to_context_cwd(tmp_path: Path) -> None:
    with workspace_scope(ExecutionPathContext.at(tmp_path)):
        written = await WriteFileTool().execute(
            WriteFileTool.params_model(path="note.txt", content="hi")
        )
        assert not written.is_error
        read = await ReadFileTool().execute(
            ReadFileTool.params_model(path="note.txt")
        )
        assert "hi" in read.content
        edited = await EditFileTool().execute(
            EditFileTool.params_model(
                path="note.txt",
                old_string="hi",
                new_string="hello",
            )
        )
        assert not edited.is_error
        globbed = await GlobTool().execute(
            GlobTool.params_model(pattern="*.txt", path=".")
        )
        assert "note.txt" in globbed.content
        grepped = await GrepTool().execute(
            GrepTool.params_model(pattern="hello", path=".")
        )
        assert "note.txt" in grepped.content


@pytest.mark.asyncio
async def test_file_tools_reject_escape_paths(tmp_path: Path) -> None:
    with workspace_scope(ExecutionPathContext.at(tmp_path)):
        result = await WriteFileTool().execute(
            WriteFileTool.params_model(path="../evil.txt", content="x")
        )
        assert result.is_error
        result = await ReadFileTool().execute(
            ReadFileTool.params_model(path="/etc/passwd")
        )
        assert result.is_error


@pytest.mark.asyncio
async def test_bash_uses_context_cwd(tmp_path: Path, monkeypatch) -> None:
    with workspace_scope(ExecutionPathContext.at(tmp_path)):
        tool = BashTool()

        captured: dict[str, object] = {}

        class FakeStream:
            async def read(self, n: int) -> bytes:
                return b""

        class FakeProcess:
            stdout = FakeStream()
            stderr = FakeStream()
            returncode = 0

            async def wait(self) -> int:
                return 0

        async def fake_create(*args: object, **kwargs: object) -> FakeProcess:
            captured["cwd"] = kwargs.get("cwd")
            return FakeProcess()

        monkeypatch.setattr(
            asyncio,
            "create_subprocess_shell",
            fake_create,
        )
        await tool.execute(BashTool.params_model(command="pwd"))
        assert captured["cwd"] == str(tmp_path.resolve())


def test_main_process_never_calls_chdir(tmp_path: Path, monkeypatch) -> None:
    import os

    calls: list[str] = []
    original = os.chdir

    def spy(path: object) -> None:
        calls.append(str(path))
        original(path)

    monkeypatch.setattr(os, "chdir", spy)
    with workspace_scope(ExecutionPathContext.at(tmp_path)):
        resolve_path("x.txt", Access.READ)
    assert calls == []
