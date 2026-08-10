"""应用层：唯一 composition root 与会话服务边界。"""

from .bootstrap import build_runtime
from .runtime import ApplicationRuntime
from .session import SessionService

__all__ = [
    "ApplicationRuntime",
    "SessionService",
    "build_runtime",
]
