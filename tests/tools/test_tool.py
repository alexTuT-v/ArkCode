"""工具注册中心与六个内置工具的行为测试。"""

import asyncio
import json
import multiprocessing
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from Arkcode.llm import ROLE_TOOL, Message, StreamEnd
from Arkcode.tools import Registry, Result, new_default_registry
from Arkcode.tools.base import Tool, ToolDefinition
from Arkcode.tools.builtins.bash import _read_bounded_stream
from Arkcode.tools.builtins.grep import GrepTool, _search_in_subprocess
from Arkcode.tools.builtins.grep import Params as GrepParams
from Arkcode.tools.builtins.read_file import Params as ReadParams
from Arkcode.tools.builtins.read_file import ReadFileTool
from Arkcode.tools.workspace import ExecutionPathContext, workspace_scope


@pytest.fixture(autouse=True)
def _workspace_boundary(tmp_path: Path):
    """工具按新语义需要在显式 workspace 边界内执行。"""

    with workspace_scope(ExecutionPathContext.at(tmp_path)):
        yield


def test_tool_message_defaults_to_empty_results() -> None:
    message = Message(role=ROLE_TOOL)

    assert message.content == ""
    assert message.tool_results == []


def test_stream_event_carries_per_request_usage() -> None:
    event = StreamEnd("stop", input_tokens=12, output_tokens=7)

    assert (event.input_tokens, event.output_tokens) == (12, 7)


def test_tool_contracts_are_owned_by_tool_package() -> None:
    definition = ToolDefinition(
        name="example",
        description="example tool",
        input_schema={"type": "object"},
    )
    result = Result("ok")

    assert definition.name == "example"
    assert result.content == "ok"
    assert isinstance(ReadFileTool(), Tool)


def test_registry_exports_six_ordered_tools_and_finds_by_name() -> None:
    registry = new_default_registry()

    assert [item.name for item in registry.definitions()] == [
        "read_file",
        "write_file",
        "edit_file",
        "bash",
        "glob",
        "grep",
    ]
    assert registry.get("read_file") is not None
    assert registry.get("missing") is None


def test_registry_exports_only_read_only_tools_in_registration_order() -> None:
    registry = new_default_registry()

    assert [item.name for item in registry.read_only_definitions()] == [
        "read_file",
        "glob",
        "grep",
    ]
    assert registry.is_read_only("read_file") is True
    assert registry.is_read_only("write_file") is False
    assert registry.is_read_only("missing") is False
    assert isinstance(registry, Registry)


@pytest.mark.asyncio
async def test_read_file_adds_line_numbers_and_reports_missing_file(tmp_path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("first\nsecond\n")
    registry = new_default_registry()

    result = await registry.execute("read_file", f'{{"path": "{path}"}}')
    missing = await registry.execute(
        "read_file", f'{{"path": "{tmp_path / "missing.txt"}"}}'
    )

    assert result.is_error is False
    assert "     1\tfirst" in result.content
    assert "     2\tsecond" in result.content
    assert missing.is_error is True


@pytest.mark.asyncio
async def test_write_file_creates_parent_directories_and_overwrites(tmp_path) -> None:
    path = tmp_path / "a" / "b" / "sample.txt"
    registry = new_default_registry()

    first = await registry.execute(
        "write_file", f'{{"path": "{path}", "content": "first"}}'
    )
    second = await registry.execute(
        "write_file", f'{{"path": "{path}", "content": "second"}}'
    )

    assert first.is_error is False
    assert second.is_error is False
    assert path.read_text() == "second"


@pytest.mark.asyncio
async def test_edit_file_requires_exactly_one_match(tmp_path) -> None:
    registry = new_default_registry()
    unique_path = tmp_path / "unique.txt"
    unique_path.write_text("before")
    missing_path = tmp_path / "missing.txt"
    missing_path.write_text("different")
    repeated_path = tmp_path / "repeated.txt"
    repeated_path.write_text("same same")

    unique = await registry.execute(
        "edit_file",
        f'{{"path": "{unique_path}", "old_string": "before", "new_string": "after"}}',
    )
    missing = await registry.execute(
        "edit_file",
        f'{{"path": "{missing_path}", "old_string": "before", "new_string": "after"}}',
    )
    repeated = await registry.execute(
        "edit_file",
        f'{{"path": "{repeated_path}", "old_string": "same", "new_string": "after"}}',
    )

    assert unique.is_error is False
    assert unique_path.read_text() == "after"
    assert missing.is_error is True
    assert "未找到" in missing.content
    assert repeated.is_error is True
    assert "2" in repeated.content
    assert missing.content != repeated.content


@pytest.mark.asyncio
async def test_bash_returns_output_exit_code_and_timeout() -> None:
    registry = new_default_registry()

    result = await registry.execute(
        "bash", '{"command": "printf hi; printf problem >&2; exit 3"}'
    )
    timeout = await registry.execute("bash", '{"command": "sleep 5"}', timeout=0.01)

    assert result.is_error is False
    assert "exit_code: 3" in result.content
    assert "hi" in result.content
    assert "problem" in result.content
    assert timeout.is_error is True
    assert "超时" in timeout.content


def test_tool_descriptions_reinforce_dedicated_read_and_read_before_edit() -> None:
    registry = new_default_registry()
    bash = registry.get("bash")
    edit = registry.get("edit_file")

    assert bash is not None
    assert edit is not None
    bash_description = bash.description()
    edit_description = edit.description()
    assert all(name in bash_description for name in ("read_file", "glob", "grep"))
    assert "优先" in bash_description
    assert "read_file" in edit_description
    assert "编辑前" in edit_description


@pytest.mark.asyncio
async def test_bash_bounds_output_while_command_is_running() -> None:
    registry = new_default_registry()
    command = f"{sys.executable} -c " + json.dumps(
        "import sys; sys.stdout.write('x' * 1_000_000)"
    )

    result = await registry.execute("bash", json.dumps({"command": command}))

    assert result.is_error is False
    assert result.content.endswith("[truncated]")
    assert len(result.content) <= 30_100


@pytest.mark.asyncio
async def test_bash_stream_reader_discards_bytes_above_memory_limit() -> None:
    stream = asyncio.StreamReader()
    stream.feed_data(b"x" * 1_000_000)
    stream.feed_eof()

    retained, truncated = await _read_bounded_stream(stream, 15_000)

    assert len(retained) == 15_000
    assert truncated is True


@pytest.mark.skipif(os.name != "posix", reason="进程组断言仅适用于 POSIX")
@pytest.mark.asyncio
async def test_bash_timeout_terminates_descendant_processes(tmp_path) -> None:
    registry = new_default_registry()
    pid_file = tmp_path / "child.pid"
    command = f"sleep 30 & echo $! > {pid_file}; wait"
    child_pid = 0

    try:
        result = await registry.execute(
            "bash",
            json.dumps({"command": command}),
            timeout=0.2,
        )
        child_pid = int(pid_file.read_text())

        assert result.is_error is True
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        if child_pid:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.asyncio
async def test_read_file_does_not_block_event_loop(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "slow.txt"
    path.write_text("content")
    original = Path.open

    def slow_open(self: Path, *args, **kwargs):
        time.sleep(0.05)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", slow_open)
    task = asyncio.create_task(ReadFileTool().execute(ReadParams(path=str(path))))

    await asyncio.sleep(0.01)

    assert task.done() is False
    await task


@pytest.mark.asyncio
async def test_grep_does_not_block_event_loop_and_bounds_long_line(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "slow.txt"
    path.write_text("needle" + "x" * 1_100_000)
    original = Path.open

    def slow_open(self: Path, *args, **kwargs):
        time.sleep(0.05)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", slow_open)
    task = asyncio.create_task(
        GrepTool().execute(GrepParams(path=str(path), pattern="needle"))
    )

    await asyncio.sleep(0.01)

    assert task.done() is False
    result = await task
    assert len(result.content) < 5_000
    assert "line truncated" in result.content


@pytest.mark.asyncio
async def test_grep_cancellation_terminates_worker_process(tmp_path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("needle\n")
    task = asyncio.create_task(_search_in_subprocess(str(path), "needle", None))
    await asyncio.sleep(0)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert not any(
        child.name == "ArkCodeGrep" for child in multiprocessing.active_children()
    )


@pytest.mark.asyncio
async def test_glob_and_grep_return_bounded_matches(tmp_path) -> None:
    (tmp_path / "nested").mkdir()
    source = tmp_path / "nested" / "sample.py"
    source.write_text("needle = 1\n")
    registry = new_default_registry()

    glob_result = await registry.execute(
        "glob", f'{{"pattern": "**/*.py", "path": "{tmp_path}"}}'
    )
    grep_result = await registry.execute(
        "grep", f'{{"pattern": "needle", "path": "{tmp_path}"}}'
    )

    assert glob_result.is_error is False
    assert str(source) in glob_result.content
    assert grep_result.is_error is False
    assert f"{source}:1:needle = 1" in grep_result.content


@pytest.mark.asyncio
async def test_registry_turns_unknown_tool_and_invalid_json_into_errors() -> None:
    registry = new_default_registry()

    unknown = await registry.execute("missing", "{}")
    malformed = await registry.execute("read_file", "{")

    assert unknown.is_error is True
    assert "未知工具" in unknown.content
    assert malformed.is_error is True
