"""tmux 后端：split-window / detached new-session。"""

from __future__ import annotations

import asyncio
import os

from ..models import BackendType, SpawnRequest, SpawnResult


def _member_command(request: SpawnRequest) -> list[str]:
    command = [
        "python",
        "-m",
        "Arkcode",
        "--team-member",
        "--team",
        request.team_name,
        "--member",
        request.member_name,
        "--agent-id",
        request.agent_id,
        "--session-dir",
        request.session_dir,
        "--worktree",
        request.worktree_path,
    ]
    if request.agent_type:
        command += ["--agent-type", request.agent_type]
    if request.model:
        command += ["--model", request.model]
    if request.plan_mode_required:
        command.append("--plan-mode")
    return command


class TmuxBackend:
    def type(self) -> BackendType:
        return BackendType.TMUX

    async def spawn(self, request: SpawnRequest) -> SpawnResult:
        inside_session = bool(os.environ.get("TMUX"))
        if inside_session:
            args = [
                "tmux",
                "split-window",
                "-h",
                "-P",
                "-F",
                "#{pane_id}",
                "--",
                *_member_command(request),
            ]
        else:
            args = [
                "tmux",
                "new-session",
                "-d",
                "-P",
                "-F",
                "#{pane_id}",
                "--",
                *_member_command(request),
            ]
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                f"tmux spawn 失败: {stderr.decode(errors='replace').strip()}"
            )
        pane_id = stdout.decode(errors="replace").strip()
        if not pane_id:
            raise RuntimeError("tmux 未返回 pane_id")
        return SpawnResult(
            pane_id=pane_id,
            agent_id=request.agent_id,
            backend=self.type(),
        )

    async def wake(self, pane_id: str, agent_id: str) -> None:
        await asyncio.create_subprocess_exec(
            "tmux",
            "send-keys",
            "-t",
            pane_id,
            "",
            "Enter",
        )

    async def kill(self, pane_id: str, agent_id: str) -> None:
        await asyncio.create_subprocess_exec(
            "tmux",
            "kill-pane",
            "-t",
            pane_id,
        )

    async def is_alive(self, pane_id: str, agent_id: str) -> bool:
        process = await asyncio.create_subprocess_exec(
            "tmux",
            "list-panes",
            "-t",
            pane_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        return process.returncode == 0
