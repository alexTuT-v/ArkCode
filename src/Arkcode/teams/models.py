"""Team 领域的数据模型。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from .storage import FileLock


class BackendType(StrEnum):
    TMUX = "tmux"
    ITERM2 = "iterm2"
    IN_PROCESS = "in-process"


class MessageType(StrEnum):
    TEXT = "text"
    SHUTDOWN_REQUEST = "shutdown_request"
    SHUTDOWN_RESPONSE = "shutdown_response"
    PLAN_APPROVAL_REQUEST = "plan_approval_request"
    PLAN_APPROVAL_RESPONSE = "plan_approval_response"


@dataclass(slots=True)
class Message:
    """跨进程邮箱消息（requestId 序列化为 camelCase）。"""

    from_agent: str
    text: str
    timestamp: str
    read: bool
    type: MessageType = MessageType.TEXT
    request_id: str = ""
    approve: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "from": self.from_agent,
            "text": self.text,
            "timestamp": self.timestamp,
            "read": self.read,
        }
        if self.type is not MessageType.TEXT:
            value["type"] = self.type.value
        if self.request_id:
            value["requestId"] = self.request_id
        if self.approve is not None:
            value["approve"] = self.approve
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Message:
        raw_type = str(value.get("type", "text"))
        try:
            message_type = MessageType(raw_type)
        except ValueError:
            message_type = MessageType.TEXT
        approve = value.get("approve")
        return cls(
            from_agent=str(value.get("from", "")),
            text=str(value.get("text", "")),
            timestamp=str(value.get("timestamp", "")),
            read=bool(value.get("read", False)),
            type=message_type,
            request_id=str(value.get("requestId", "")),
            approve=approve if isinstance(approve, bool) else None,
        )


@dataclass(slots=True)
class TeammateInfo:
    name: str
    agent_id: str
    agent_type: str
    model: str
    worktree_path: str
    branch: str
    backend_type: BackendType
    pane_id: str
    is_active: bool | None
    plan_mode_required: bool
    session_dir: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "model": self.model,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "backend_type": self.backend_type.value,
            "pane_id": self.pane_id,
            "is_active": self.is_active,
            "plan_mode_required": self.plan_mode_required,
            "session_dir": self.session_dir,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TeammateInfo:
        try:
            backend = BackendType(str(value["backend_type"]))
        except (KeyError, ValueError):
            backend = BackendType.IN_PROCESS
        return cls(
            name=str(value["name"]),
            agent_id=str(value["agent_id"]),
            agent_type=str(value.get("agent_type", "")),
            model=str(value.get("model", "")),
            worktree_path=str(value.get("worktree_path", "")),
            branch=str(value.get("branch", "")),
            backend_type=backend,
            pane_id=str(value.get("pane_id", "")),
            is_active=value.get("is_active"),
            plan_mode_required=bool(value.get("plan_mode_required", False)),
            session_dir=str(value.get("session_dir", "")),
        )


@dataclass(slots=True)
class Team:
    """一个持久化团队对象；Lead 独立保存，members 只含队员。"""

    name: str
    sanitized_name: str
    description: str
    lead_agent_id: str
    members: list[TeammateInfo]
    config_dir: Path
    config_path: Path
    created_at: datetime
    backend: BackendType
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def config_lock(self) -> FileLock:
        return FileLock(self.config_path.with_suffix(".json.lock"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sanitized_name": self.sanitized_name,
            "description": self.description,
            "lead_agent_id": self.lead_agent_id,
            "backend": self.backend.value,
            "created_at": self.created_at.isoformat(),
            "members": [member.to_dict() for member in self.members],
        }

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        config_dir: Path,
    ) -> Team:
        config_path = config_dir / "config.json"
        try:
            backend = BackendType(str(value.get("backend", "in-process")))
        except ValueError:
            backend = BackendType.IN_PROCESS
        created = value.get("created_at")
        try:
            created_at = datetime.fromisoformat(str(created))
        except (TypeError, ValueError):
            created_at = datetime.now().astimezone()
        return cls(
            name=str(value.get("name", "")),
            sanitized_name=str(value.get("sanitized_name", config_dir.name)),
            description=str(value.get("description", "")),
            lead_agent_id=str(value.get("lead_agent_id", "lead")),
            members=[
                TeammateInfo.from_dict(item)
                for item in value.get("members", [])
                if isinstance(item, dict)
            ],
            config_dir=config_dir,
            config_path=config_path,
            created_at=created_at,
            backend=backend,
        )


@dataclass(frozen=True, slots=True)
class SpawnRequest:
    team_name: str
    member_name: str
    agent_id: str
    worktree_path: str
    session_dir: str
    agent_type: str
    model: str
    initial_prompt: str
    plan_mode_required: bool
    agent: object | None = None
    conversation: object | None = None


@dataclass(frozen=True, slots=True)
class SpawnResult:
    pane_id: str
    agent_id: str
    backend: BackendType


class SharedTaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass(slots=True)
class SharedTask:
    id: str
    title: str
    description: str
    status: SharedTaskStatus
    assignee: str
    blocked_by: list[str]
    blocks: list[str]
    created_at: int
    updated_at: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "assignee": self.assignee,
            "blocked_by": self.blocked_by,
            "blocks": self.blocks,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SharedTask:
        try:
            status = SharedTaskStatus(str(value.get("status", "pending")))
        except ValueError:
            status = SharedTaskStatus.PENDING
        return cls(
            id=str(value["id"]),
            title=str(value.get("title", "")),
            description=str(value.get("description", "")),
            status=status,
            assignee=str(value.get("assignee", "")),
            blocked_by=[str(item) for item in value.get("blocked_by", [])],
            blocks=[str(item) for item in value.get("blocks", [])],
            created_at=int(value.get("created_at", 0)),
            updated_at=int(value.get("updated_at", 0)),
        )
