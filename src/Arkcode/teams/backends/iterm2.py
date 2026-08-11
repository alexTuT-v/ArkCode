"""iTerm2 后端（通过 it2 CLI）。"""

from __future__ import annotations

import asyncio
import shlex

from ..models import BackendType, SpawnRequest, SpawnResult
from .tmux import _member_command


class Iterm2Backend:
    def type(self) -> BackendType:
        return BackendType.ITERM2

    async def spawn(self, request: SpawnRequest) -> SpawnResult:
        command = shlex.join(_member_command(request))
        process = await asyncio.create_subprocess_exec(
            "it2",
            "split",
            "--new-pane",
            "--command",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                f"it2 spawn 失败: {stderr.decode(errors='replace').strip()}"
            )
        pane_id = stdout.decode(errors="replace").strip()
        if not pane_id:
            raise RuntimeError("it2 未返回 pane id")
        return SpawnResult(
            pane_id=pane_id,
            agent_id=request.agent_id,
            backend=self.type(),
        )

    async def wake(self, pane_id: str, agent_id: str) -> None:
        await asyncio.create_subprocess_exec(
            "it2",
            "send-text",
            "--pane",
            pane_id,
            "",
        )

    async def kill(self, pane_id: str, agent_id: str) -> None:
        await asyncio.create_subprocess_exec(
            "it2",
            "close-pane",
            "--pane",
            pane_id,
        )

    async def is_alive(self, pane_id: str, agent_id: str) -> bool:
        process = await asyncio.create_subprocess_exec(
            "it2",
            "list-panes",
            "--pane",
            pane_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        return process.returncode == 0
