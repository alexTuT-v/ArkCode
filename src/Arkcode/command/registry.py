"""命令注册、冲突检测与补全查询。"""

from .command import Command


class Registry:
    def __init__(self) -> None:
        self._by_name: dict[str, Command] = {}
        self._visible: list[Command] = []

    def register(self, command: Command, *, replace: bool = False) -> None:
        keys = (command.name, *command.aliases)
        if any(not key or key != key.lower() for key in keys):
            raise ValueError("command names and aliases must be non-empty lowercase")
        seen: set[str] = set()
        for key in keys:
            if key in seen:
                raise RuntimeError(f"command conflict: {key}")
            seen.add(key)
            if not replace and key in self._by_name:
                raise RuntimeError(f"command conflict: {key}")
        if replace:
            replaced = {
                id(self._by_name[key]): self._by_name[key]
                for key in keys
                if key in self._by_name
            }
            for old in replaced.values():
                self._remove(old)
        for key in keys:
            self._by_name[key] = command
        if not command.hidden:
            self._visible.append(command)
            self._visible.sort(key=lambda item: item.name)

    def _remove(self, command: Command) -> None:
        self._by_name = {
            key: item for key, item in self._by_name.items() if item is not command
        }
        self._visible = [item for item in self._visible if item is not command]

    def clear(self) -> None:
        self._by_name.clear()
        self._visible.clear()

    def lookup(self, name: str) -> Command | None:
        return self._by_name.get(name.lower())

    def visible(self) -> list[Command]:
        return list(self._visible)

    def prefix_match(self, prefix: str) -> list[Command]:
        normalized = prefix.lstrip("/").lower()
        return [item for item in self._visible if item.name.startswith(normalized)]
