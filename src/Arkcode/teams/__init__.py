"""Agent Team 领域的公共导出。"""

from .backends.detect import detect_backend
from .mailbox import Box
from .manager import TeamManager
from .models import (
    BackendType,
    Message,
    MessageType,
    SharedTask,
    SharedTaskStatus,
    SpawnRequest,
    SpawnResult,
    Team,
    TeammateInfo,
)
from .registry import AgentNameRegistry
from .shared_tasks import SharedTaskStore
from .storage import FileLock, atomic_update_json

__all__ = [
    "AgentNameRegistry",
    "BackendType",
    "Box",
    "FileLock",
    "Message",
    "MessageType",
    "SharedTask",
    "SharedTaskStatus",
    "SharedTaskStore",
    "SpawnRequest",
    "SpawnResult",
    "Team",
    "TeamManager",
    "TeammateInfo",
    "atomic_update_json",
    "detect_backend",
]
