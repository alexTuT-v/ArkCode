"""基于格式 v2 元数据的过期会话清理。"""

from __future__ import annotations

import logging
import shutil
from datetime import timedelta
from pathlib import Path

from .meta import SessionMetaStore

logger = logging.getLogger(__name__)


def clean_expired(sessions_dir: str, max_age: timedelta) -> None:
    """按 meta.created_at 删除过期目录，跳过旧格式与损坏 meta 目录。"""

    root = Path(sessions_dir)
    if not root.is_dir():
        return
    from datetime import datetime

    now = datetime.now().astimezone()
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        meta = SessionMetaStore(directory).load()
        if meta is None:
            continue
        if now - meta.created_at <= max_age:
            continue
        try:
            shutil.rmtree(directory)
        except OSError:
            logger.warning("清理过期会话失败: %s", directory, exc_info=True)
