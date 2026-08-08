"""Skill 系统公共入口。"""

from .executor import SYSTEM_TOOL_NAMES, SkillExecutor
from .install import (
    MAX_FILE_COUNT,
    MAX_FILE_SIZE,
    MAX_RECURSION_DEPTH,
    MAX_TOTAL_SIZE,
    SkillInstallError,
    SkillSource,
    install_skill,
    parse_skill_url,
)
from .loader import SkillLoader
from .parser import (
    SkillMeta,
    SkillParseError,
    parse_frontmatter,
    parse_skill_file,
    substitute_arguments,
)

__all__ = [
    "SYSTEM_TOOL_NAMES",
    "MAX_FILE_COUNT",
    "MAX_FILE_SIZE",
    "MAX_RECURSION_DEPTH",
    "MAX_TOTAL_SIZE",
    "SkillExecutor",
    "SkillInstallError",
    "SkillLoader",
    "SkillMeta",
    "SkillParseError",
    "SkillSource",
    "install_skill",
    "parse_frontmatter",
    "parse_skill_file",
    "parse_skill_url",
    "substitute_arguments",
]
