"""会话列表、筛选与恢复控制。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text
from textual.events import Key
from textual.widgets import RichLog

from ...context.constants import AUTO_SAFETY_MARGIN, SUMMARY_RESERVE
from ...context.tokens import estimate_tokens
from ...permissions import Mode
from ...sessions import SessionInfo, last_message_timestamp, list_sessions, load_session
from ..state import SessionState

if TYPE_CHECKING:
    from ...application import SessionService
    from ..app import ArkCodeApp


def _relative_time(value: datetime) -> str:
    now = datetime.now().astimezone()
    if value.tzinfo is None:
        value = value.astimezone()
    seconds = max(0, int((now - value).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} minutes ago"
    if seconds < 86400:
        return f"{seconds // 3600} hours ago"
    return f"{seconds // 86400} days ago"


def _size(value: int) -> str:
    if value < 1024:
        return f"{value}B"
    return f"{value / 1024:.1f}KB"


@dataclass(frozen=True)
class SessionItem:
    info: SessionInfo

    @property
    def display_text(self) -> str:
        return (
            f"{self.info.title} · {_relative_time(self.info.modified_at)} · "
            f"{self.info.model or 'unknown model'} · {_size(self.info.size)}"
        )


class SessionController:
    def __init__(self, app: ArkCodeApp, session: SessionService) -> None:
        self._app = app
        self._session = session

    def begin_resume(self) -> None:
        """扫描会话并进入选择状态。"""

        app = self._app
        app.resume_items = [
            SessionItem(info)
            for info in list_sessions(app.sessions_dir)
            if info.id != self._session.runtime.session.session_id
        ]
        app.resume_query = ""
        if not app.resume_items:
            app.query_one("#log", RichLog).write(Text("没有可恢复的会话", style="dim"))
            return
        app.state = SessionState.RESUMING
        app.query_one("#input").disabled = True
        self._show_items()

    def cancel_resume(self) -> None:
        app = self._app
        app.resume_list.display = False
        app.state = SessionState.IDLE
        input_box = app.query_one("#input")
        input_box.disabled = False
        input_box.focus()

    async def handle_key(self, event: Key) -> None:
        """处理搜索、确认和取消按键。"""

        app = self._app
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.cancel_resume()
            return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            index = app.resume_list.highlighted
            if index is not None and index < len(app.resume_filtered):
                await self.resume(app.resume_filtered[index].info)
            return
        if event.key == "backspace":
            event.prevent_default()
            event.stop()
            app.resume_query = app.resume_query[:-1]
            self._show_items()
            return
        character = getattr(event, "character", None)
        if character and character.isprintable():
            event.prevent_default()
            event.stop()
            app.resume_query += character
            self._show_items()

    def _show_items(self) -> None:
        app = self._app
        query = app.resume_query.casefold()
        app.resume_filtered = [
            item
            for item in app.resume_items
            if query in item.display_text.casefold() or query in item.info.id.casefold()
        ]
        app.resume_list.set_options([item.display_text for item in app.resume_filtered])
        if app.resume_filtered:
            app.resume_list.highlighted = 0
        app.resume_list.display = True
        app.resume_list.focus()

    async def resume(self, info: SessionInfo) -> None:
        """切换到选定会话，并在必要时压缩或追加过期提醒。"""

        app = self._app
        messages = load_session(info.dir)
        loaded_count = len(messages)
        timestamp = last_message_timestamp(info.dir)
        self._session.resume_session(info)

        threshold = (
            self._session.runtime.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
        )
        agent = self._session.agent
        if agent is not None and estimate_tokens(0, messages, 0) >= threshold:
            definitions = (
                app.tool_registry.read_only_definitions()
                if self._session.mode is Mode.PLAN
                else app.tool_registry.definitions()
            )
            try:
                await agent.run_force_compact(self._session.conversation, definitions)
            except Exception as error:
                app.query_one("#log", RichLog).write(
                    Text(f"恢复后压缩失败：{error}", style="dim")
                )

        if timestamp is not None:
            elapsed = int(time.time()) - timestamp
            if elapsed > 6 * 3600:
                duration = self._pause_duration(elapsed)
                self._session.conversation.add_user(
                    f"[系统提示] 本会话已暂停 {duration}。部分上下文可能已过时，"
                    "如需最新信息请重新读取相关文件。"
                )

        self.cancel_resume()
        app.query_one("#log", RichLog).write(
            Text(f"已恢复会话 {info.id}，共 {loaded_count} 条消息", style="dim")
        )

    @staticmethod
    def _pause_duration(seconds: int) -> str:
        if seconds >= 86400:
            return f"{seconds // 86400} 天"
        if seconds >= 3600:
            return f"{seconds // 3600} 小时"
        return f"{max(1, seconds // 60)} 分钟"
