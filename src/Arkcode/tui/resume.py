"""会话列表展示、筛选与恢复流程。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual.events import Key
from textual.widgets import RichLog

from ..compact import open_session_context
from ..compact.const import AUTO_SAFETY_MARGIN, SUMMARY_RESERVE
from ..compact.token import estimate_tokens
from ..conversation import Conversation
from ..permission import Mode
from ..session import (
    SessionInfo,
    Writer,
    last_message_timestamp,
    list_sessions,
    load_session,
)

if TYPE_CHECKING:
    from .app import ArkCodeApp


def _relative_time(value: datetime) -> str:
    seconds = max(0, int((datetime.now() - value).total_seconds()))
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


def _show_items(app: ArkCodeApp) -> None:
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


def begin_resume(app: ArkCodeApp) -> None:
    """扫描会话并进入选择状态。"""

    app.resume_items = [
        SessionItem(info)
        for info in list_sessions(app.sessions_dir)
        if info.id != app.runtime.session.session_id
    ]
    app.resume_query = ""
    if not app.resume_items:
        app.query_one("#log", RichLog).write(Text("没有可恢复的会话", style="dim"))
        return
    app.state = type(app.state).RESUMING
    app.query_one("#input").disabled = True
    _show_items(app)


def cancel_resume(app: ArkCodeApp) -> None:
    app.resume_list.display = False
    app.state = type(app.state).IDLE
    input_box = app.query_one("#input")
    input_box.disabled = False
    input_box.focus()


async def handle_resume_key(app: ArkCodeApp, event: Key) -> None:
    """处理搜索、确认和取消按键。"""

    if event.key == "escape":
        event.prevent_default()
        event.stop()
        cancel_resume(app)
        return
    if event.key == "enter":
        event.prevent_default()
        event.stop()
        index = app.resume_list.highlighted
        if index is not None and index < len(app.resume_filtered):
            await do_resume_session(app, app.resume_filtered[index].info)
        return
    if event.key == "backspace":
        event.prevent_default()
        event.stop()
        app.resume_query = app.resume_query[:-1]
        _show_items(app)
        return
    character = getattr(event, "character", None)
    if character and character.isprintable():
        event.prevent_default()
        event.stop()
        app.resume_query += character
        _show_items(app)


def _pause_duration(seconds: int) -> str:
    if seconds >= 86400:
        return f"{seconds // 86400} 天"
    if seconds >= 3600:
        return f"{seconds // 3600} 小时"
    return f"{max(1, seconds // 60)} 分钟"


async def do_resume_session(app: ArkCodeApp, info: SessionInfo) -> None:
    """切换到选定会话，并在必要时压缩或追加过期提醒。"""

    messages = load_session(info.dir)
    loaded_count = len(messages)
    timestamp = last_message_timestamp(info.dir)
    new_writer = Writer.open_existing(info.dir)
    if app.provider is not None:
        new_writer.set_model(app.provider.model)
    new_conv = Conversation.from_messages(
        messages,
        on_append=new_writer.on_append,
        on_replace=new_writer.on_replace,
    )
    workspace = str(Path(app.sessions_dir).parent.parent)
    new_context = open_session_context(workspace, info.id)

    old_writer = app.writer
    app.writer = new_writer
    app.conv = new_conv
    app.runtime.session = new_context
    old_writer.close()

    threshold = app.runtime.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
    if app.agent is not None and estimate_tokens(0, messages, 0) >= threshold:
        definitions = (
            app._tool_registry.read_only_definitions()
            if app.mode is Mode.PLAN
            else app._tool_registry.definitions()
        )
        try:
            await app.agent.run_force_compact(app.conv, definitions)
        except Exception as error:
            app.query_one("#log", RichLog).write(
                Text(f"恢复后压缩失败：{error}", style="dim")
            )

    if timestamp is not None:
        elapsed = int(time.time()) - timestamp
        if elapsed > 6 * 3600:
            duration = _pause_duration(elapsed)
            app.conv.add_user(
                f"[系统提示] 本会话已暂停 {duration}。部分上下文可能已过时，"
                "如需最新信息请重新读取相关文件。"
            )

    cancel_resume(app)
    app.query_one("#log", RichLog).write(
        Text(f"已恢复会话 {info.id}，共 {loaded_count} 条消息", style="dim")
    )
