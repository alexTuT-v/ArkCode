"""消费 AgentEvent 并驱动宿主界面更新的流式控制器。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

from rich.console import RenderableType
from rich.markdown import Markdown
from rich.text import Text

from ...agents import AgentEvent, ApprovalRequest, Phase, Usage
from ..views.messages import format_compact_notice, render_markdown
from ..views.tools import tool_line, tool_result_summary
from .state import StreamingState, ToolDisplay


class StreamingHost(Protocol):
    """流式控制器所需的宿主界面能力。"""

    def write_log(self, renderable: RenderableType) -> None: ...

    async def wait_for_streaming_refresh(self) -> None: ...

    def refresh_streaming_view(self) -> None: ...

    def finish_turn(self) -> None: ...

    def finish_with_error(self, error: Exception) -> None: ...

    def update_usage(self, usage: Usage) -> None: ...

    def set_approval(self, request: ApprovalRequest) -> None: ...

    def elapsed(self) -> float: ...


class StreamingController:
    """把 AgentEvent 转换为展示状态与宿主回调，不直接接触 Provider 或工具注册表。"""

    def __init__(self, host: StreamingHost) -> None:
        self._host = host
        self.state = StreamingState()

    def reset(self) -> None:
        self.state = StreamingState()

    async def consume(self, events: AsyncIterator[AgentEvent]) -> None:
        pending_error: Exception | None = None
        try:
            async for event in events:
                if event.compact is not None:
                    self._host.write_log(
                        Text(format_compact_notice(event.compact), style="dim")
                    )
                    await self._host.wait_for_streaming_refresh()
                    continue
                if event.approval is not None:
                    self._host.set_approval(event.approval)
                    continue
                if event.err is not None:
                    pending_error = event.err
                    continue
                if event.iter:
                    self.state.iteration = event.iter
                    self._host.refresh_streaming_view()
                if event.usage is not None:
                    self._host.update_usage(event.usage)
                if event.thinking:
                    self.state.thinking += event.thinking
                    self._host.refresh_streaming_view()
                if event.notice:
                    self._host.write_log(Text(event.notice, style="dim"))
                if event.text:
                    self.state.reply += event.text
                    self.state.thinking = ""
                    self._host.refresh_streaming_view()
                    # 兼容一次性吐出多个已缓冲事件的端点，确保至少绘制一帧。
                    await self._host.wait_for_streaming_refresh()
                if event.tool is not None and event.tool.phase is Phase.START:
                    if self.state.reply:
                        self._host.write_log(Markdown(self.state.reply))
                        self.state.reply = ""
                    self.state.tools.append(
                        ToolDisplay(event.tool.name, event.tool.args)
                    )
                    self._host.refresh_streaming_view()
                if event.tool is not None and event.tool.phase is Phase.END:
                    display = (
                        self.state.tools.pop(0)
                        if self.state.tools
                        else ToolDisplay(event.tool.name, event.tool.args)
                    )
                    self._host.write_log(tool_line(display.name, display.args))
                    self._host.write_log(
                        tool_result_summary(
                            event.tool.result,
                            event.tool.is_error,
                        )
                    )
                    self._host.refresh_streaming_view()
                if event.done:
                    if self.state.reply:
                        self._host.write_log(
                            render_markdown(self.state.reply, self._host.elapsed())
                        )
                    self._host.finish_turn()
                    return
            if pending_error is not None:
                self._host.finish_with_error(pending_error)
                return
            if self.state.reply:
                self._host.write_log(
                    render_markdown(self.state.reply, self._host.elapsed())
                )
            self._host.finish_turn()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._host.finish_with_error(exc)
