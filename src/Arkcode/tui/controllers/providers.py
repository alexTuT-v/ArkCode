"""Provider 选择与激活控制。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import OptionList

from ..state import SessionState
from ..widgets.message_input import MessageInput

if TYPE_CHECKING:
    from ...application import SessionService
    from ...config import ProviderConfig
    from ..app import ArkCodeApp


class ProviderController:
    def __init__(self, app: ArkCodeApp, session: SessionService) -> None:
        self._app = app
        self._session = session

    def activate(self, config: ProviderConfig) -> None:
        """激活选中 Provider，并完成 Skill 工具与命令表的接线。"""

        self._session.activate_provider(config)
        agent = self._session.agent
        if agent is not None:
            self._app.load_skill_tool.set_agent(agent)
        if self._session.skill_executor is not None:
            self._app.skills.register_dynamic_commands()
        self.show_chat_layout()

    def show_selection(self) -> None:
        app = self._app
        app.state = SessionState.SELECTING
        for selector in (
            "#log",
            "#streaming",
            "#input-row",
            "#input",
            "#prompt",
            "#statusbar",
        ):
            app.query_one(selector).display = False
        app.query_one("#provider-select", OptionList).focus()

    def show_chat_layout(self) -> None:
        app = self._app
        app.state = SessionState.IDLE
        option_list = app.query("#provider-select")
        if option_list:
            option_list.first().display = False
        for selector in (
            "#log",
            "#streaming",
            "#input-row",
            "#input",
            "#prompt",
            "#statusbar",
        ):
            app.query_one(selector).display = True
        app.update_statusbar()
        app.query_one("#input", MessageInput).focus()
