"""模型流消费逻辑。"""

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, cast

from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import RichLog

from ..agent import Agent, ApprovalRequest, Phase
from ..conversation import Conversation
from ..llm import Provider
from ..permission import Engine, Mode, Outcome
from ..tool import Registry
from .commands import format_compact_notice
from .view import render_markdown, tool_line, tool_result_summary


@dataclass(frozen=True)
class ToolDisplay:
    """动态区当前正在执行的工具。"""

    name: str
    args: str


class StreamControllerMixin:
    """为 ``ArkCodeApp`` 提供异步流消费流程。"""

    provider: Provider | None
    conv: Conversation
    cur_reply: str
    cur_thinking: str
    cur_tools: list[ToolDisplay]
    iter: int
    mode: Mode
    usage_in: int
    usage_out: int
    usage_cache_read: int
    usage_cache_creation: int
    turn_cancel: asyncio.Event | None
    _tool_registry: Registry
    _version: str
    engine: Engine | None
    pending: ApprovalRequest | None
    agent: Agent | None
    approve_cursor: int
    state: Any

    def _refresh_streaming_view(self) -> None:
        raise NotImplementedError

    async def _wait_for_streaming_refresh(self) -> None:
        raise NotImplementedError

    def _finish_with_assistant(self, reply: str) -> None:
        raise NotImplementedError

    def _finish_with_error(self, error: Exception) -> None:
        raise NotImplementedError

    def _finish_turn(self) -> None:
        raise NotImplementedError

    def _elapsed(self) -> float:
        raise NotImplementedError

    def _update_statusbar(self) -> None:
        raise NotImplementedError

    async def _consume_agent_events(self) -> None:
        provider = self.provider
        if provider is None:
            self._finish_with_error(RuntimeError("尚未选择 provider"))
            return

        pending_error: Exception | None = None
        try:
            agent = self.agent
            if agent is None:
                self._finish_with_error(RuntimeError("Agent 尚未初始化"))
                return
            cancel = self.turn_cancel
            if cancel is None:
                self._finish_with_error(RuntimeError("本轮取消事件未初始化"))
                return
            async for event in agent.run(self.conv, self.mode, cancel):
                if event.compact is not None:
                    cast(Any, self).query_one("#log", RichLog).write(
                        Text(format_compact_notice(event.compact), style="dim")
                    )
                    await self._wait_for_streaming_refresh()
                    continue
                if event.approval is not None:
                    self.pending = event.approval
                    self.approve_cursor = 0
                    self.state = type(self.state).APPROVING
                    self._refresh_streaming_view()
                    continue
                if event.err is not None:
                    pending_error = event.err
                    continue
                if event.iter:
                    self.iter = event.iter
                    self._refresh_streaming_view()
                if event.usage is not None:
                    self.usage_in += event.usage.input
                    self.usage_out += event.usage.output
                    self.usage_cache_read += event.usage.cache_read
                    self.usage_cache_creation += event.usage.cache_creation
                    self._update_statusbar()
                if event.thinking:
                    self.cur_thinking += event.thinking
                    self._refresh_streaming_view()
                if event.notice:
                    cast(Any, self).query_one("#log", RichLog).write(
                        Text(event.notice, style="dim")
                    )
                if event.text:
                    self.cur_reply += event.text
                    self.cur_thinking = ""
                    self._refresh_streaming_view()
                    # 兼容一次性吐出多个已缓冲事件的端点，确保至少绘制一帧。
                    await self._wait_for_streaming_refresh()
                if event.tool is not None and event.tool.phase is Phase.START:
                    if self.cur_reply:
                        cast(Any, self).query_one("#log", RichLog).write(
                            Markdown(self.cur_reply)
                        )
                        self.cur_reply = ""
                    self.cur_tools.append(ToolDisplay(event.tool.name, event.tool.args))
                    self._refresh_streaming_view()
                if event.tool is not None and event.tool.phase is Phase.END:
                    log = cast(Any, self).query_one("#log", RichLog)
                    display = (
                        self.cur_tools.pop(0)
                        if self.cur_tools
                        else ToolDisplay(event.tool.name, event.tool.args)
                    )
                    log.write(tool_line(display.name, display.args))
                    log.write(
                        tool_result_summary(
                            event.tool.result,
                            event.tool.is_error,
                        )
                    )
                    self._refresh_streaming_view()
                if event.done:
                    if self.cur_reply:
                        cast(Any, self).query_one("#log", RichLog).write(
                            render_markdown(self.cur_reply, self._elapsed())
                        )
                    self._finish_turn()
                    return
            if pending_error is not None:
                self._finish_with_error(pending_error)
                return
            if self.cur_reply:
                cast(Any, self).query_one("#log", RichLog).write(
                    render_markdown(self.cur_reply, self._elapsed())
                )
            self._finish_turn()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._finish_with_error(exc)

    def update_approving(self, key: str) -> None:
        """更新批准菜单光标，或把所选结果送回暂停中的 Agent。"""

        request = self.pending
        if request is None:
            return
        if key in {"up", "k"}:
            self.approve_cursor = (self.approve_cursor - 1) % 3
            self._refresh_streaming_view()
            return
        if key in {"down", "j"}:
            self.approve_cursor = (self.approve_cursor + 1) % 3
            self._refresh_streaming_view()
            return

        indexes = {"1": 0, "2": 1, "3": 2}
        if key in indexes:
            self.approve_cursor = indexes[key]
        elif key == "y":
            self.approve_cursor = 0
        elif key in {"n", "d"}:
            self.approve_cursor = 2
        elif key not in {"enter", "space"}:
            return

        outcomes = (
            Outcome.ALLOW_ONCE,
            Outcome.ALLOW_FOREVER,
            Outcome.DENY_ONCE,
        )
        outcome = outcomes[self.approve_cursor]
        self.pending = None
        self.state = type(self.state).STREAMING
        self._refresh_streaming_view()
        if not request.respond.done():
            request.respond.set_result(outcome)


StreamCoroutine = Coroutine[Any, Any, None]
