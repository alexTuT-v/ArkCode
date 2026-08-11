"""tmux Team 端到端（无 tmux 时明确 SKIP）。"""

import shutil

import pytest

tmux_available = shutil.which("tmux") is not None

pytestmark = pytest.mark.skipif(
    not tmux_available,
    reason="当前环境没有 tmux，跳过真实 pane 集成测试",
)


@pytest.mark.asyncio
async def test_tmux_team_spawn_creates_pane() -> None:
    from Arkcode.teams.backends.tmux import TmuxBackend
    from Arkcode.teams.models import SpawnRequest

    backend = TmuxBackend()
    result = await backend.spawn(
        SpawnRequest(
            team_name="demo",
            member_name="alice",
            agent_id="agent-alice",
            worktree_path="/tmp/wt",
            session_dir="/tmp/s",
            agent_type="general-purpose",
            model="",
            initial_prompt="任务",
            plan_mode_required=False,
        )
    )
    assert result.pane_id
    await backend.kill(result.pane_id, result.agent_id)
