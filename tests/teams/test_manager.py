"""TeamManager 生命周期、sanitize 与并发成员更新测试。"""

import json
from pathlib import Path

import pytest

from Arkcode.teams.manager import (
    TeamHasActiveMembersError,
    TeamManager,
    sanitize_team_name,
)
from Arkcode.teams.models import BackendType, TeammateInfo


def make_manager(tmp_path: Path) -> TeamManager:
    return TeamManager(tmp_path / "home")


def member(name: str = "alice") -> TeammateInfo:
    return TeammateInfo(
        name=name,
        agent_id=f"agent-{name}",
        agent_type="general-purpose",
        model="",
        worktree_path="/wt",
        branch=f"worktree-team-x+{name}",
        backend_type=BackendType.IN_PROCESS,
        pane_id="",
        is_active=True,
        plan_mode_required=False,
        session_dir="/sessions/x",
    )


def test_sanitize_team_name() -> None:
    assert sanitize_team_name("refactor auth") == "refactor-auth"
    assert sanitize_team_name("  demo  ") == "demo"
    with pytest.raises(ValueError):
        sanitize_team_name("!!!")


@pytest.mark.asyncio
async def test_create_writes_config_with_lead_and_empty_members(
    tmp_path: Path,
) -> None:
    manager = make_manager(tmp_path)
    team = await manager.create("refactor auth")
    assert team.sanitized_name == "refactor-auth"
    assert team.lead_agent_id == "lead"
    assert team.members == []
    assert team.config_path.is_file()
    value = json.loads(team.config_path.read_text(encoding="utf-8"))
    assert value["lead_agent_id"] == "lead"
    assert value["members"] == []
    assert value["backend"] in {"tmux", "iterm2", "in-process"}


@pytest.mark.asyncio
async def test_same_name_gets_suffix(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    first = await manager.create("demo")
    second = await manager.create("demo")
    assert first.sanitized_name == "demo"
    assert second.sanitized_name == "demo-2"
    assert second.config_path == (
        first.config_path.parent.parent / "demo-2" / "config.json"
    )


@pytest.mark.asyncio
async def test_scan_restores_teams(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    await manager.create("alpha")
    reopened = make_manager(tmp_path)
    assert reopened.get("alpha") is not None


@pytest.mark.asyncio
async def test_add_and_set_member_active(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    team = await manager.create("demo")
    await manager.add_member("demo", member("bob"))
    assert len(team.members) == 1
    assert team.members[0].is_active is True
    await manager.set_member_active("demo", "bob", False)
    assert team.members[0].is_active is False
    with pytest.raises(Exception):
        await manager.set_member_active("demo", "ghost", False)


@pytest.mark.asyncio
async def test_delete_rejects_active_without_force(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    await manager.create("demo")
    await manager.add_member("demo", member())
    with pytest.raises(TeamHasActiveMembersError):
        await manager.delete("demo", False)
    assert (tmp_path / "home" / ".Arkcode" / "teams" / "demo").is_dir()


@pytest.mark.asyncio
async def test_force_delete_cleans_dirs(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    await manager.create("demo")
    await manager.add_member("demo", member())
    session_dir = tmp_path / "sessions" / "x"
    session_dir.mkdir(parents=True, exist_ok=True)
    await manager.delete("demo", True)
    assert not (tmp_path / "home" / ".Arkcode" / "teams" / "demo").exists()


@pytest.mark.asyncio
async def test_concurrent_add_member_keeps_all(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    await manager.create("demo")
    import asyncio

    await asyncio.gather(
        *(manager.add_member("demo", member(f"m{i}")) for i in range(5))
    )
    assert len(manager.get("demo").members) == 5  # type: ignore[union-attr]
