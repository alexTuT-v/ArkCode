"""Coordinator Mode：双锁开关、精确白名单与调度提示词。"""

from __future__ import annotations

import os
from typing import Any

COORDINATOR_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "Agent",
        "SendMessage",
        "JobStop",
        "TeamDelete",
    }
)

COORDINATOR_SYSTEM_PROMPT_SUFFIX = (
    "\n\n<coordinator-mode>\n"
    "你现在是纯调度 Coordinator。\n"
    "- 只能使用 Agent、SendMessage、JobStop、TeamDelete 四个工具。\n"
    "- 派完队员就停手等汇报：不得自行探索、读写文件或执行 shell。\n"
    "- 不要用 sleep / JobList / TaskList 轮询凑时间；完成后等系统通知唤醒。\n"
    "- 每轮只需发一行总结，例如：已派 N 名队员探索 X，等结果。\n"
    "- 队员完成前不要 TeamDelete；收敛合并在退出 Coordinator 后用普通模式执行。\n"
    "</coordinator-mode>"
)


def env_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def feature_has(config: Any, name: str) -> bool:
    if name != "COORDINATOR_MODE":
        return False
    features = getattr(config, "features", None)
    if features is None:
        return False
    return bool(getattr(features, "coordinator_mode", False))


def is_enabled(config: Any) -> bool:
    if not feature_has(config, "COORDINATOR_MODE"):
        return False
    return env_truthy(os.environ.get("ArkCODE_COORDINATOR_MODE", ""))
