"""模型流消费逻辑。"""

import asyncio
from collections.abc import Coroutine
from typing import Any

from ..conversation import Conversation
from ..llm import Provider


class StreamControllerMixin:
    """为 ``ArkCodeApp`` 提供异步流消费流程。"""

    provider: Provider | None
    conv: Conversation
    cur_reply: str

    def _refresh_streaming_view(self) -> None:
        raise NotImplementedError

    async def _wait_for_streaming_refresh(self) -> None:
        raise NotImplementedError

    def _finish_with_assistant(self, reply: str) -> None:
        raise NotImplementedError

    def _finish_with_error(self, error: Exception) -> None:
        raise NotImplementedError

    async def _consume_stream(self) -> None:
        provider = self.provider
        if provider is None:
            self._finish_with_error(RuntimeError("尚未选择 provider"))
            return

        try:
            async for event in provider.stream(self.conv.messages()):
                if event.err is not None:
                    self._finish_with_error(event.err)
                    return
                if event.text:
                    self.cur_reply += event.text
                    self._refresh_streaming_view()
                    # 兼容一次性吐出多个已缓冲事件的端点，确保至少绘制一帧。
                    await self._wait_for_streaming_refresh()
                if event.done:
                    self._finish_with_assistant(self.cur_reply)
                    return
            self._finish_with_assistant(self.cur_reply)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._finish_with_error(exc)


StreamCoroutine = Coroutine[Any, Any, None]
