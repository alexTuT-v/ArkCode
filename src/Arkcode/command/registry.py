"""命令注册、冲突检测与补全查询。"""

from .command import Command


class Registry:
    def __init__(self) -> None:
        self._by_name: dict[str, Command] = {}
        self._visible: list[Command] = []

    def register(self, command: Command) -> None:
        keys = (command.name, *command.aliases)
        if any(not key or key != key.lower() for key in keys):
            raise ValueError("command names and aliases must be non-empty lowercase")
        seen: set[str] = set()
        for key in keys:
            if key in seen or key in self._by_name:
                raise RuntimeError(f"command conflict: {key}")
            seen.add(key)
        for key in keys:
            self._by_name[key] = command
        if not command.hidden:
            self._visible.append(command)
            self._visible.sort(key=lambda item: item.name)

    def lookup(self, name: str) -> Command | None:
        return self._by_name.get(name.lower())

    def visible(self) -> list[Command]:
        return list(self._visible)

    def prefix_match(self, prefix: str) -> list[Command]:
        normalized = prefix.lstrip("/").lower()
        return [item for item in self._visible if item.name.startswith(normalized)]
