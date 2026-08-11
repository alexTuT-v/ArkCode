"""单级 Markdown 记忆文件存储。"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .types import MemoryEntry, MemoryScope, NoteType, UpdateAction

_FILENAME_RE = re.compile(
    rf"^(?:{'|'.join(item.value for item in NoteType)})_"
    r"[a-z0-9]+(?:_[a-z0-9]+)*\.md$"
)
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


class Store:
    """管理项目级或用户级的一组笔记与索引。"""

    def __init__(self, dir: str) -> None:
        self._dir = Path(dir)
        self._lock = threading.Lock()

    def ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def load_index(self) -> str:
        path = self._dir / "MEMORY.md"
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def clear(self) -> None:
        """删除目录内全部笔记并重建索引；MEMORY.md 本身保留。"""

        with self._lock:
            for path in self._dir.glob("*.md"):
                if path.name == "MEMORY.md":
                    continue
                try:
                    path.unlink()
                except OSError:
                    pass
            self._rebuild_index()

    @staticmethod
    def _parse_note(path: Path) -> tuple[dict[str, Any], str]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError(f"记忆笔记缺少 frontmatter: {path.name}")
        _, raw_meta, content = text.split("---\n", 2)
        metadata = yaml.safe_load(raw_meta) or {}
        if not isinstance(metadata, dict):
            raise ValueError(f"记忆笔记 frontmatter 无效: {path.name}")
        return metadata, content.strip()

    @staticmethod
    def _render(metadata: dict[str, Any], content: str) -> str:
        frontmatter = yaml.safe_dump(
            metadata,
            allow_unicode=True,
            sort_keys=False,
        ).strip()
        return f"---\n{frontmatter}\n---\n{content.strip()}\n"

    @staticmethod
    def validate_filename(filename: str) -> None:
        if not _FILENAME_RE.fullmatch(filename):
            raise ValueError(f"非法记忆文件名: {filename}")

    @staticmethod
    def validate_slug(slug: str) -> None:
        if not _SLUG_RE.fullmatch(slug):
            raise ValueError(f"非法记忆 slug: {slug}")

    def read(self, filename: str) -> str:
        self.validate_filename(filename)
        return (self._dir / filename).read_text(encoding="utf-8")

    def list_entries(self, scope: MemoryScope) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        for path in sorted(self._dir.glob("*.md")):
            if path.name == "MEMORY.md" or not _FILENAME_RE.fullmatch(path.name):
                continue
            try:
                metadata, content = self._parse_note(path)
                note_type = NoteType(str(metadata["type"]))
            except (KeyError, OSError, ValueError, yaml.YAMLError):
                continue
            entries.append(
                MemoryEntry(
                    scope=scope,
                    type=note_type,
                    filename=path.name,
                    title=str(metadata.get("title", path.stem)),
                    preview=" ".join(content.split())[:100],
                    updated_at=str(metadata.get("updated", "")),
                )
            )
            if len(entries) >= 200:
                break
        return entries

    def rebuild_index(self) -> None:
        with self._lock:
            self.ensure_dir()
            self._rebuild_index()

    def _rebuild_index(self) -> None:
        lines: list[str] = []
        for path in sorted(self._dir.glob("*.md")):
            if path.name == "MEMORY.md" or not _FILENAME_RE.fullmatch(path.name):
                continue
            try:
                metadata, content = self._parse_note(path)
            except (OSError, ValueError, yaml.YAMLError):
                continue
            note_type = str(metadata.get("type", ""))
            title = str(metadata.get("title", path.stem))
            description = " ".join(content.split())[:100]
            lines.append(f"- [{note_type}] {title} — {description}")
            if len(lines) >= 200:
                break
        index = "\n".join(lines)
        if index:
            index += "\n"
        (self._dir / "MEMORY.md").write_text(index, encoding="utf-8")

    def apply(self, actions: list[UpdateAction]) -> None:
        with self._lock:
            self.ensure_dir()
            for action in actions:
                now = datetime.now().astimezone().isoformat()
                if action.action == "create":
                    note_type = NoteType(action.type)
                    self.validate_slug(action.slug)
                    filename = f"{note_type.value}_{action.slug}.md"
                    self.validate_filename(filename)
                    path = self._dir / filename
                    if path.exists():
                        metadata, _ = self._parse_note(path)
                        metadata["type"] = note_type.value
                        metadata["title"] = action.title
                        metadata["updated"] = now
                    else:
                        metadata = {
                            "type": note_type.value,
                            "title": action.title,
                            "created": now,
                            "updated": now,
                        }
                    path.write_text(
                        self._render(metadata, action.content), encoding="utf-8"
                    )
                elif action.action == "update":
                    self.validate_filename(action.filename)
                    path = self._dir / action.filename
                    metadata, old_content = self._parse_note(path)
                    metadata["title"] = action.title or metadata.get("title", "")
                    metadata["updated"] = now
                    content = action.content or old_content
                    path.write_text(self._render(metadata, content), encoding="utf-8")
                elif action.action == "delete":
                    self.validate_filename(action.filename)
                    (self._dir / action.filename).unlink(missing_ok=True)
                else:
                    raise ValueError(f"未知记忆操作: {action.action}")
            self._rebuild_index()
