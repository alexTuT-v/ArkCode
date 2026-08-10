"""底部状态栏组件。"""

from textual.widgets import Static

from ...llm import Provider
from ...permissions import Mode
from ..views.status import status_bar


class StatusBar(Static):
    """按模型与用量数据刷新状态栏内容。"""

    def set_status(
        self,
        provider: Provider,
        mode: Mode,
        usage_in: int,
        usage_out: int,
        usage_cache_read: int,
        usage_cache_creation: int,
    ) -> None:
        self.update(
            status_bar(
                provider,
                mode,
                usage_in,
                usage_out,
                usage_cache_read,
                usage_cache_creation,
            )
        )
