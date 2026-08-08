"""清理过期的新版会话目录。"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from ..compact.state import parse_session_time

logger = logging.getLogger(__name__)


def clean_expired(sessions_dir: str, max_age: timedelta) -> None:
    """按会话 ID 创建时间删除过期目录，保留旧格式目录。"""

    root = Path(sessions_dir)
    if not root.is_dir():
        return
    now = datetime.now()
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        try:
            created_at = parse_session_time(directory.name)
        except ValueError:
            continue
        if now - created_at <= max_age:
            continue
        try:
            shutil.rmtree(directory)
        except OSError:
            logger.warning("清理过期会话失败: %s", directory, exc_info=True)
