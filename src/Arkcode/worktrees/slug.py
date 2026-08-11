"""Worktree slug 验证与 flatten。"""

from __future__ import annotations

import re

SEGMENT_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
MAX_SLUG_LENGTH = 64


def validate_slug(name: str) -> None:
    """校验 slug；非法时抛 ValueError 并携带具体原因。"""

    if not name:
        raise ValueError("slug 不能为空")
    if len(name) > MAX_SLUG_LENGTH:
        raise ValueError(f"slug 总长度超过 {MAX_SLUG_LENGTH}")
    if name.startswith("/") or name.endswith("/"):
        raise ValueError("slug 不允许首尾斜杠")
    if "//" in name:
        raise ValueError("slug 不允许连续斜杠")
    for segment in name.split("/"):
        if segment in {".", ".."}:
            raise ValueError(f"slug 段 {segment!r} 不允许")
        if SEGMENT_RE.fullmatch(segment) is None:
            raise ValueError(
                f"slug 段 {segment!r} 仅允许 [a-zA-Z0-9._-]"
            )


def flatten_slug(name: str) -> str:
    """把嵌套 slug 的 / 替换为 +，避免 Git D/F 冲突。"""

    return name.replace("/", "+")
