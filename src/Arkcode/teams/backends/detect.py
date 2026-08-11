"""后端一次性检测，不做运行时回退。"""

from __future__ import annotations

import os
import shutil

from ..models import BackendType

_cached: BackendType | None = None


def detect_backend() -> BackendType:
    """按 TMUX → iTerm2+it2 → PATH tmux → in-process 优先级选择一次。"""

    global _cached
    if _cached is not None:
        return _cached
    if os.environ.get("TMUX"):
        _cached = BackendType.TMUX
    elif os.environ.get("TERM_PROGRAM") == "iTerm.app" and shutil.which("it2"):
        _cached = BackendType.ITERM2
    elif shutil.which("tmux"):
        _cached = BackendType.TMUX
    else:
        _cached = BackendType.IN_PROCESS
    return _cached


def reset_backend_cache() -> None:
    global _cached
    _cached = None
