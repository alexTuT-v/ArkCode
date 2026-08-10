"""Slash 补全键盘交互控制。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.events import Key
from textual.widgets import Static

from ..widgets.message_input import MessageInput

if TYPE_CHECKING:
    from ..app import ArkCodeApp


class CompletionController:
    def __init__(self, app: ArkCodeApp) -> None:
        self._app = app

    def update_from_input(self, text: str) -> None:
        self._app.completion.update(text, self._app.cmd_registry)
        self.render()

    def render(self) -> None:
        self._app.query_one("#completion", Static).update(
            self._app.completion.render(max(1, self._app.size.width - 8))
        )

    async def handle_key(self, event: Key) -> bool:
        completion = self._app.completion
        if not completion.active:
            return False
        if event.key == "up":
            completion.move_up()
        elif event.key == "down":
            completion.move_down()
        elif event.key == "escape":
            completion.hide()
        elif event.key in {"enter", "tab"}:
            selected = completion.selected()
            if selected is not None:
                input_box = self._app.query_one("#input", MessageInput)
                input_box.text = "/" + selected.name
                await self._app.submit(input_box.text)
            elif event.key == "enter":
                input_box = self._app.query_one("#input", MessageInput)
                await self._app.submit(input_box.text)
            else:
                completion.hide()
        else:
            return False
        event.prevent_default()
        event.stop()
        self.render()
        return True
