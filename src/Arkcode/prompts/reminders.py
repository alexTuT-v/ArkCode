"""动态补充指令与规划模式提醒。"""

EXECUTE_DIRECTIVE = "请按上面的计划开始执行。"

_PLAN_REMINDER_FULL = (
    "You are in PLAN MODE. Use only read-only tools (read_file, glob, grep) to "
    "investigate. Do not write, edit, or run shell commands. Produce a step-by-step "
    "plan, then wait for /do approval."
)
_PLAN_REMINDER_CONCISE = (
    "PLAN MODE remains active: use only read-only tools and continue toward a plan; "
    "wait for /do before executing changes."
)


def system_reminder(body: str) -> str:
    """标记一条动态系统补充，避免被视为用户提问。"""

    return f"<system-reminder>\n{body}\n</system-reminder>"


def plan_reminder(full: bool) -> str:
    """生成完整或精简的规划模式补充指令。"""

    return system_reminder(_PLAN_REMINDER_FULL if full else _PLAN_REMINDER_CONCISE)


def deferred_tools_reminder(names: list[str]) -> str:
    """把尚未发现的延迟工具名渲染为请求级系统提醒。"""

    if not names:
        return ""
    body = (
        "The following deferred tools are available via ToolSearch. "
        "Their schemas are not loaded. Use ToolSearch with query "
        '"select:<name>[,<name>...]" before calling them:\n\n'
        + "\n".join(names)
    )
    return system_reminder(body)


def combine_reminders(*items: str) -> str:
    """连接非空的、已包装的请求级提醒。"""

    return "\n\n".join(item for item in items if item)
