"""Slash Command 自动补全状态机。"""

from dataclasses import dataclass, field

from rich.text import Text

from ..command import Command, Registry

MAX_ROWS = 8


@dataclass(slots=True)
class CompletionMenu:
    items: list[Command] = field(default_factory=list)
    cursor: int = 0
    offset: int = 0
    active: bool = False

    def update(self, input_text: str, registry: Registry) -> None:
        value = input_text.rstrip()
        if "\n" in input_text or not input_text.startswith("/"):
            self.hide()
            return
        self.items = registry.prefix_match(value)
        self.active = True
        self.cursor = min(self.cursor, max(0, len(self.items) - 1))
        self._follow_cursor()

    def _follow_cursor(self) -> None:
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + MAX_ROWS:
            self.offset = self.cursor - MAX_ROWS + 1

    def move_up(self) -> None:
        if self.items:
            self.cursor = max(0, self.cursor - 1)
            self._follow_cursor()

    def move_down(self) -> None:
        if self.items:
            self.cursor = min(len(self.items) - 1, self.cursor + 1)
            self._follow_cursor()

    def selected(self) -> Command | None:
        return self.items[self.cursor] if self.items else None

    def hide(self) -> None:
        self.items = []
        self.cursor = 0
        self.offset = 0
        self.active = False

    def render(self, width: int) -> Text:
        if not self.active:
            return Text()
        if not self.items:
            return Text("无匹配", style="dim")
        name_width = max(len(item.name) for item in self.items)
        result = Text()
        if self.offset:
            result.append(f"↑ {self.offset} more\n", style="dim")
        visible = self.items[self.offset : self.offset + MAX_ROWS]
        for index, item in enumerate(visible, start=self.offset):
            line = f"/{item.name.ljust(name_width)}  {item.description}"[:width]
            result.append(line, style="reverse" if index == self.cursor else "")
            result.append("\n")
        remaining = len(self.items) - self.offset - len(visible)
        if remaining:
            result.append(f"↓ {remaining} more", style="dim")
        return result
