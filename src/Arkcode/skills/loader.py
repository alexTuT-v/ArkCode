"""本地 Skill 的分层发现、缓存与热重载。"""

import logging
from pathlib import Path
from typing import Literal

from .parser import SkillMeta, SkillParseError, parse_skill_file

PROJECT_SKILLS_DIR = Path(".Arkcode/skills")
USER_SKILLS_DIR = Path(".Arkcode/skills")

logger = logging.getLogger(__name__)


class SkillLoader:
    def __init__(self, work_dir: str | Path) -> None:
        self._project_dir = Path(work_dir).resolve() / PROJECT_SKILLS_DIR
        self._user_dir = Path.home().resolve() / USER_SKILLS_DIR
        self._skills: dict[str, SkillMeta] = {}
        self._cache: dict[str, SkillMeta] = {}

    def _scan_directory(
        self,
        path: Path,
        source: Literal["project", "user"],
    ) -> list[SkillMeta]:
        if not path.is_dir():
            return []
        try:
            entries = sorted(path.iterdir(), key=lambda item: item.name)
        except OSError as error:
            logger.warning("Skipping %s skills directory '%s': %s", source, path, error)
            return []
        skills: list[SkillMeta] = []
        for entry in entries:
            if entry.is_file() and entry.suffix.lower() == ".md":
                source_path = entry
                is_directory = False
            elif entry.is_dir() and (entry / "SKILL.md").is_file():
                source_path = entry / "SKILL.md"
                is_directory = True
            else:
                continue
            try:
                skills.append(parse_skill_file(source_path, is_directory=is_directory))
            except SkillParseError as error:
                logger.warning(
                    "Skipping %s skill '%s': %s",
                    source,
                    entry.name,
                    error,
                )
        return skills

    def load_all(self) -> list[SkillMeta]:
        loaded: dict[str, SkillMeta] = {}
        locations: tuple[
            tuple[Path, Literal["project", "user"]],
            ...,
        ] = (
            (self._project_dir, "project"),
            (self._user_dir, "user"),
        )
        for path, source in locations:
            for skill in self._scan_directory(path, source):
                loaded.setdefault(skill.name, skill)
        self._skills = loaded
        self._cache = dict(loaded)
        return self._ordered()

    def reload(self) -> list[SkillMeta]:
        return self.load_all()

    def _ordered(self) -> list[SkillMeta]:
        return [self._skills[name] for name in sorted(self._skills)]

    def get(self, name: str) -> SkillMeta | None:
        normalized = name.lower()
        current = self._skills.get(normalized)
        if current is None:
            return None
        try:
            refreshed = parse_skill_file(
                current.source_path,
                is_directory=current.is_directory,
            )
            if refreshed.name != normalized:
                raise SkillParseError(
                    f"hot-reloaded name changed from {normalized} to {refreshed.name}"
                )
        except SkillParseError as error:
            logger.warning("Failed to reload skill '%s': %s", normalized, error)
            return self._cache.get(normalized)
        self._skills[normalized] = refreshed
        self._cache[normalized] = refreshed
        return refreshed

    def get_catalog(self) -> list[tuple[str, str]]:
        return [(skill.name, skill.description) for skill in self._ordered()]

    def get_source_label(
        self,
        name: str,
    ) -> Literal["project", "user"] | None:
        skill = self._skills.get(name.lower())
        if skill is None:
            return None
        if skill.source_path.is_relative_to(self._project_dir):
            return "project"
        if skill.source_path.is_relative_to(self._user_dir):
            return "user"
        return None
