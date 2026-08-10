"""长期记忆的数据类型。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class NoteType(StrEnum):
    USER_PREFERENCE = "user_preference"
    CORRECTION_FEEDBACK = "correction_feedback"
    PROJECT_KNOWLEDGE = "project_knowledge"
    REFERENCE_MATERIAL = "reference_material"


class MemoryScope(StrEnum):
    PROJECT = "project"
    USER = "user"


@dataclass(frozen=True)
class MemoryEntry:
    scope: MemoryScope
    type: NoteType
    filename: str
    title: str
    preview: str
    updated_at: str

    @property
    def key(self) -> str:
        return f"{self.scope.value}:{self.filename}"


@dataclass(frozen=True)
class MemoryTurn:
    session_id: str
    turn_id: str
    user_text: str
    assistant_text: str


@dataclass
class Note:
    type: NoteType
    title: str
    slug: str
    content: str
    filename: str
    created: datetime
    updated: datetime


@dataclass
class UpdateAction:
    action: str
    level: str
    type: str = ""
    title: str = ""
    slug: str = ""
    content: str = ""
    filename: str = ""
