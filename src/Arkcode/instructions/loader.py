"""安全加载 ArkCODE.md 及其 include 指令。"""

from __future__ import annotations

import os
import re
from pathlib import Path

_INCLUDE_RE = re.compile(r"^@include\s+(.+)$")


class Loader:
    """按项目、项目隐藏目录、用户目录的优先级加载指令。"""

    def __init__(
        self,
        project_root: str | Path,
        user_home: str | Path | None = None,
        *,
        max_depth: int = 5,
    ) -> None:
        self.project_root = Path(project_root)
        self.user_home = Path(user_home or os.path.expanduser("~"))
        self.max_depth = max_depth

    def load(self) -> str:
        """加载所有存在的入口文件，并以空行分隔。"""

        sources = (
            (self.project_root / "ArkCODE.md", self.project_root),
            (self.project_root / ".Arkcode" / "ArkCODE.md", self.project_root),
            (self.user_home / ".Arkcode" / "ArkCODE.md", self.user_home),
        )
        loaded = [
            content
            for path, boundary in sources
            if (content := self._load_file(path, boundary, 0, set()))
        ]
        return "\n\n".join(loaded)

    def _load_file(
        self,
        path: Path,
        boundary: Path,
        depth: int,
        visited: set[Path],
    ) -> str:
        if depth > self.max_depth:
            return f"<!-- 超过最大嵌套深度（超过最大 include 深度）: {path} -->"

        resolved = Path(os.path.realpath(path))
        resolved_boundary = Path(os.path.realpath(boundary))
        if resolved in visited:
            return f"<!-- 检测到环路（include 环路）: {resolved} -->"
        if not resolved.is_relative_to(resolved_boundary):
            return f"<!-- 路径超出允许范围（include 越出允许目录）: {resolved} -->"
        if not resolved.is_file():
            return ""

        raw = resolved.read_bytes()
        if b"\x00" in raw[:512]:
            return f"<!-- 已跳过二进制文件: {resolved} -->"
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return f"<!-- 已跳过非 UTF-8 二进制文件: {resolved} -->"

        chain = visited | {resolved}
        output: list[str] = []
        for line in text.splitlines():
            match = _INCLUDE_RE.fullmatch(line)
            if match is None:
                output.append(line)
                continue
            included = resolved.parent / match.group(1).strip()
            output.append(
                self._load_file(included, resolved_boundary, depth + 1, chain)
            )
        return "\n".join(output)
