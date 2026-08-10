"""审批键盘输入控制。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...permissions import Outcome
from ..state import SessionState

if TYPE_CHECKING:
    from ..app import ArkCodeApp


class ApprovalController:
    def __init__(self, app: ArkCodeApp) -> None:
        self._app = app

    def update(self, key: str) -> None:
        """更新批准菜单光标，或把所选结果送回暂停中的 Agent。"""

        request = self._app.pending
        if request is None:
            return
        if key in {"up", "k"}:
            self._app.approve_cursor = (self._app.approve_cursor - 1) % 3
            self._app.refresh_streaming_view()
            return
        if key in {"down", "j"}:
            self._app.approve_cursor = (self._app.approve_cursor + 1) % 3
            self._app.refresh_streaming_view()
            return

        indexes = {"1": 0, "2": 1, "3": 2}
        if key in indexes:
            self._app.approve_cursor = indexes[key]
        elif key == "y":
            self._app.approve_cursor = 0
        elif key in {"n", "d"}:
            self._app.approve_cursor = 2
        elif key not in {"enter", "space"}:
            return

        outcomes = (
            Outcome.ALLOW_ONCE,
            Outcome.ALLOW_FOREVER,
            Outcome.DENY_ONCE,
        )
        outcome = outcomes[self._app.approve_cursor]
        self._app.pending = None
        self._app.state = SessionState.STREAMING
        self._app.refresh_streaming_view()
        if not request.respond.done():
            request.respond.set_result(outcome)

    def cancel(self) -> None:
        """取消当前审批：把拒绝结果送回等待中的请求。"""

        request = self._app.pending
        if request is not None and not request.respond.done():
            request.respond.set_result(Outcome.DENY_ONCE)
