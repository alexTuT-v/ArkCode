"""Agent 定义的三层来源加载与覆盖。"""

from __future__ import annotations

import sys
from importlib import resources
from pathlib import Path

from .models import Definition, Source
from .parser import DefinitionParseError, parse_definition, parse_definition_file


class Catalog:
    """按 builtin → user → project 顺序加载，后加载覆盖前者。"""

    def __init__(
        self,
        project_root: str | Path | None = None,
        user_root: str | Path | None = None,
    ) -> None:
        self._project_root = Path(project_root or Path.cwd()).resolve()
        self._user_root = Path(user_root or Path.home()).resolve()
        self._definitions: dict[str, Definition] = {}
        self._warnings: list[str] = []

    def load(self) -> None:
        self._definitions = {}
        self._warnings = []
        self._load_builtins()
        self._load_dir(self._user_root / ".Arkcode" / "agents", Source.USER)
        self._load_dir(self._project_root / ".Arkcode" / "agents", Source.PROJECT)

    def reload(self) -> None:
        self.load()

    def resolve(self, name: str) -> Definition | None:
        return self._definitions.get(name)

    def list_definitions(self) -> list[tuple[str, str]]:
        """列出全部已加载定义（(name, description)）。"""

        return [
            (name, definition.description)
            for name, definition in sorted(self._definitions.items())
        ]

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def _load_builtins(self) -> None:
        try:
            package = resources.files("Arkcode.subagents").joinpath("builtins")
            for entry in sorted(
                package.iterdir(),
                key=lambda item: item.name,
            ):
                if not entry.name.endswith(".md"):
                    continue
                definition = parse_definition(
                    entry.read_text(encoding="utf-8"),
                    source=Source.BUILTIN,
                )
                self._definitions[definition.name] = definition
        except Exception as exc:
            # 内置定义属于代码缺陷，fail-fast。
            raise RuntimeError(f"内置 Agent 定义加载失败: {exc}") from exc

    def _load_dir(self, directory: Path, source: Source) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*.md")):
            try:
                definition = parse_definition_file(path, source=source)
            except DefinitionParseError as exc:
                self._warnings.append(f"跳过 Agent 定义 {path}: {exc}")
                print(f"警告: 跳过 Agent 定义 {path}: {exc}", file=sys.stderr)
                continue
            self._definitions[definition.name] = definition
