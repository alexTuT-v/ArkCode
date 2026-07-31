"""在当前工作目录执行 shell 命令。"""

import asyncio
import contextlib
import json
import os
import signal
from typing import Any

from .base import Result, Tool
from .utils import truncate

_MAX_OUTPUT_BYTES = 30_000


async def _read_bounded_stream(
    stream: asyncio.StreamReader,
    limit: int,
) -> tuple[bytes, bool]:
    """持续排空管道，但只在内存中保留指定字节数。"""

    retained = bytearray()
    truncated = False
    while chunk := await stream.read(8192):
        remaining = limit - len(retained)
        if remaining > 0:
            retained.extend(chunk[:remaining])
        if len(chunk) > max(remaining, 0):
            truncated = True
    return bytes(retained), truncated


def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
    """终止 shell 及其派生进程，避免超时后后台任务继续运行。"""

    with contextlib.suppress(ProcessLookupError):
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()


class BashTool(Tool):
    """异步执行 shell 命令并捕获输出。"""

    read_only = False

    def name(self) -> str:
        return "bash"

    def description(self) -> str:
        return "在当前工作目录执行 shell 命令并返回输出和退出码。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"}
            },
            "required": ["command"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(f"参数 JSON 无效: {exc}", is_error=True)
        command = data.get("command") if isinstance(data, dict) else None
        if not isinstance(command, str) or not command:
            return Result("缺少必填参数 command", is_error=True)

        process_options: dict[str, Any] = {}
        if os.name == "posix":
            process_options["start_new_session"] = True
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **process_options,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(
            _read_bounded_stream(process.stdout, _MAX_OUTPUT_BYTES // 2)
        )
        stderr_task = asyncio.create_task(
            _read_bounded_stream(process.stderr, _MAX_OUTPUT_BYTES // 2)
        )
        try:
            await process.wait()
            (
                (stdout_bytes, stdout_truncated),
                (
                    stderr_bytes,
                    stderr_truncated,
                ),
            ) = await asyncio.gather(stdout_task, stderr_task)
        except asyncio.CancelledError:
            _kill_process_tree(process)
            await process.wait()
            stdout_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(
                stdout_task,
                stderr_task,
                return_exceptions=True,
            )
            raise
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        content = (
            f"exit_code: {process.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )
        if stdout_truncated or stderr_truncated:
            content = content.rstrip() + "\n[truncated]"
        return Result(truncate(content, max_lines=10000, max_chars=30000))
