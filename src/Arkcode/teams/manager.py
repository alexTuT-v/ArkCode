"""Team 生命周期、持久化与恢复。"""

from __future__ import annotations

import asyncio
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from ..worktrees import ExitOptions, WorktreeManager
from .backends.base import Backend
from .models import BackendType, Team, TeammateInfo
from .registry import AgentNameRegistry
from .storage import FileLock, atomic_update_json


class TeamError(RuntimeError):
    pass


class TeamNotFoundError(TeamError):
    pass


class TeamHasActiveMembersError(TeamError):
    pass


def sanitize_team_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "-", name).strip("-")
    if not cleaned:
        raise ValueError("团队名不能为空")
    return cleaned


class TeamManager:
    def __init__(
        self,
        home_dir: str | Path,
        *,
        wt_mgr: WorktreeManager | None = None,
        task_mgr: object | None = None,
        name_registry: AgentNameRegistry | None = None,
    ) -> None:
        self._home = Path(home_dir)
        self._teams_dir = self._home / ".Arkcode" / "teams"
        self._teams_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self.teams: dict[str, Team] = {}
        self._wt_mgr = wt_mgr
        self._task_mgr = task_mgr
        self._name_registry = name_registry or AgentNameRegistry()
        self._scan()

    def _scan(self) -> None:
        for directory in sorted(self._teams_dir.iterdir()):
            if not directory.is_dir():
                continue
            config_path = directory / "config.json"
            if not config_path.is_file():
                continue
            try:
                import json

                value = json.loads(config_path.read_text(encoding="utf-8"))
                team = Team.from_dict(value, config_dir=directory)
                self.teams[team.sanitized_name] = team
            except Exception as exc:
                print(
                    f"警告: 跳过 Team {directory.name}: {exc}",
                    file=sys.stderr,
                )

    def get(self, name: str) -> Team | None:
        return self.teams.get(sanitize_team_name(name)) or self.teams.get(name)

    def list(self) -> list[Team]:
        return list(self.teams.values())

    async def create(self, name: str, agent_type: str = "") -> Team:
        sanitized = sanitize_team_name(name)
        async with self._lock:
            candidate = sanitized
            suffix = 2
            while candidate in self.teams:
                candidate = f"{sanitized}-{suffix}"
                suffix += 1
            config_dir = self._teams_dir / candidate
            config_dir.mkdir(parents=True, exist_ok=True)
            from .backends.detect import detect_backend

            backend = detect_backend()
            team = Team(
                name=name,
                sanitized_name=candidate,
                description="",
                lead_agent_id="lead",
                members=[],
                config_dir=config_dir,
                config_path=config_dir / "config.json",
                created_at=datetime.now().astimezone(),
                backend=backend,
            )
            lock = FileLock(config_dir / "config.lock")
            atomic_update_json(
                team.config_path,
                lock,
                lambda _: team.to_dict(),
            )
            self.teams[candidate] = team
            return team

    def _reload_from_disk(self, team: Team) -> None:
        import json

        if not team.config_path.is_file():
            return
        value = json.loads(team.config_path.read_text(encoding="utf-8"))
        reloaded = Team.from_dict(value, config_dir=team.config_dir)
        team.members = reloaded.members
        team.description = reloaded.description
        team.backend = reloaded.backend

    async def add_member(self, team_name: str, member: TeammateInfo) -> None:
        team = self.get(team_name)
        if team is None:
            raise TeamNotFoundError(f"未知 Team: {team_name}")
        async with team._lock:
            lock = FileLock(team.config_dir / "config.lock")

            def mutate(value: object) -> object:

                data = value if isinstance(value, dict) else {}
                if not data:
                    data = team.to_dict()
                raw_members = data.get("members", [])
                members = [
                    TeammateInfo.from_dict(item)
                    for item in raw_members
                    if isinstance(item, dict)
                ]
                if any(item.name == member.name for item in members):
                    raise TeamError(f"队员名已存在: {member.name}")
                members.append(member)
                data["members"] = [item.to_dict() for item in members]
                return data

            updated = atomic_update_json(team.config_path, lock, mutate)
            team.members = [
                TeammateInfo.from_dict(item)
                for item in updated.get("members", [])
                if isinstance(item, dict)
            ]

    async def set_member_active(
        self,
        team_name: str,
        member_name: str,
        active: bool,
    ) -> None:
        team = self.get(team_name)
        if team is None:
            raise TeamNotFoundError(f"未知 Team: {team_name}")
        async with team._lock:
            lock = FileLock(team.config_dir / "config.lock")

            def mutate(value: object) -> object:
                data = value if isinstance(value, dict) else team.to_dict()
                members = [
                    TeammateInfo.from_dict(item)
                    for item in data.get("members", [])
                    if isinstance(item, dict)
                ]
                target = next(
                    (item for item in members if item.name == member_name),
                    None,
                )
                if target is None:
                    raise TeamError(f"队员不存在: {member_name}")
                target.is_active = active
                data["members"] = [item.to_dict() for item in members]
                return data

            updated = atomic_update_json(team.config_path, lock, mutate)
            team.members = [
                TeammateInfo.from_dict(item)
                for item in updated.get("members", [])
                if isinstance(item, dict)
            ]

    async def remove_member(self, team_name: str, member_name: str) -> None:
        team = self.get(team_name)
        if team is None:
            raise TeamNotFoundError(f"未知 Team: {team_name}")
        async with team._lock:
            lock = FileLock(team.config_dir / "config.lock")

            def mutate(value: object) -> object:
                data = value if isinstance(value, dict) else team.to_dict()
                members = [
                    TeammateInfo.from_dict(item)
                    for item in data.get("members", [])
                    if isinstance(item, dict)
                ]
                data["members"] = [
                    item.to_dict()
                    for item in members
                    if item.name != member_name
                ]
                return data

            updated = atomic_update_json(team.config_path, lock, mutate)
            team.members = [
                TeammateInfo.from_dict(item)
                for item in updated.get("members", [])
                if isinstance(item, dict)
            ]

    async def update_member(
        self,
        team_name: str,
        member_name: str,
        **fields: object,
    ) -> None:
        """在 config.lock 临界区内更新单个成员的字段。"""

        team = self.get(team_name)
        if team is None:
            raise TeamNotFoundError(f"未知 Team: {team_name}")
        async with team._lock:
            lock = FileLock(team.config_dir / "config.lock")

            def mutate(value: object) -> object:
                data = value if isinstance(value, dict) else team.to_dict()
                members = [
                    TeammateInfo.from_dict(item)
                    for item in data.get("members", [])
                    if isinstance(item, dict)
                ]
                target = next(
                    (item for item in members if item.name == member_name),
                    None,
                )
                if target is None:
                    raise TeamError(f"队员不存在: {member_name}")
                if "pane_id" in fields and isinstance(fields["pane_id"], str):
                    target.pane_id = fields["pane_id"]
                if "backend_type" in fields:
                    backend = fields["backend_type"]
                    try:
                        target.backend_type = BackendType(str(backend))
                    except (TypeError, ValueError):
                        pass
                if "is_active" in fields and isinstance(
                    fields["is_active"],
                    (bool, type(None)),
                ):
                    target.is_active = fields["is_active"]  # type: ignore[assignment]
                data["members"] = [item.to_dict() for item in members]
                return data

            updated = atomic_update_json(team.config_path, lock, mutate)
            team.members = [
                TeammateInfo.from_dict(item)
                for item in updated.get("members", [])
                if isinstance(item, dict)
            ]

    async def delete(self, name: str, force: bool) -> None:
        async with self._lock:
            team = self.get(name)
            if team is None:
                raise TeamNotFoundError(f"未知 Team: {name}")
            if not force and any(
                member.is_active is not False for member in team.members
            ):
                raise TeamHasActiveMembersError(
                    f"Team {team.sanitized_name} 仍有活跃队员，拒绝删除"
                )
            for member in team.members:
                backend = await self._backend_for(member.backend_type)
                try:
                    await backend.kill(member.pane_id, member.agent_id)
                except Exception:
                    pass
                shutil.rmtree(member.session_dir, ignore_errors=True)
                if self._wt_mgr is not None and member.branch:
                    try:
                        worktree_name = next(
                            (
                                item.name
                                for item in self._wt_mgr.list()
                                if item.branch == member.branch
                            ),
                            None,
                        )
                        if worktree_name is not None:
                            await self._wt_mgr.remove(
                                worktree_name,
                                ExitOptions(discard_changes=True),
                            )
                    except Exception:
                        pass
            shutil.rmtree(team.config_dir, ignore_errors=True)
            self.teams.pop(team.sanitized_name, None)

    async def stop_member(self, member_name: str) -> bool:
        for team in self.teams.values():
            member = next(
                (item for item in team.members if item.name == member_name),
                None,
            )
            if member is None:
                continue
            backend = await self._backend_for(member.backend_type)
            await backend.kill(member.pane_id, member.agent_id)
            await self.remove_member(team.sanitized_name, member_name)
            return True
        return False

    async def _backend_for(self, backend_type: BackendType) -> Backend:
        from .backends.inprocess import InProcessBackend
        from .backends.iterm2 import Iterm2Backend
        from .backends.tmux import TmuxBackend

        if backend_type is BackendType.TMUX:
            return TmuxBackend()
        if backend_type is BackendType.ITERM2:
            return Iterm2Backend()
        return InProcessBackend(self._task_mgr)  # type: ignore[arg-type]

    @property
    def name_registry(self) -> AgentNameRegistry:
        return self._name_registry
