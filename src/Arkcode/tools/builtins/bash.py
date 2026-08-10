"""在当前工作目录执行 shell 命令。"""

import asyncio
import contextlib
import os
import signal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ..base import Result, Tool
from ..utils import truncate

if TYPE_CHECKING:
    from ...sandbox import Sandbox, SandboxConfig

_MAX_OUTPUT_BYTES = 30_000


class Params(BaseModel):
    command: str = Field(description="要执行的 shell 命令")


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


class BashTool(Tool[Params]):
    """异步执行 shell 命令并捕获输出。"""

    read_only = False
    params_model = Params

    def __init__(
        self,
        sandbox: Sandbox | None = None,
        sandbox_config: SandboxConfig | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.sandbox_config = sandbox_config

    def name(self) -> str:
        return "bash"

    def description(self) -> str:
        return (
            "在当前工作目录执行 shell 命令并返回输出和退出码。"
            "读文件、找文件、搜内容请优先使用 read_file、glob、grep，"
            "不要用 bash 拼凑。"
        )

    async def execute(self, params: Params) -> Result:
        command = params.command

        actual_command = command
        if (
            self.sandbox is not None
            and self.sandbox_config is not None
            and self.sandbox.available()
        ):
            actual_command = self.sandbox.wrap(command, self.sandbox_config)

        process_options: dict[str, Any] = {}
        if os.name == "posix":
            process_options["start_new_session"] = True
        process = await asyncio.create_subprocess_shell(
            actual_command,
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
