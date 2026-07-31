"""应用内置提示词与启动横幅。"""

from rich.text import Text

SYSTEM_PROMPT = """\
You are ArkCode, a precise and helpful AI coding agent. You can read, create,
and edit files, execute shell commands, find files, and search source code
through the tools provided to you. Use a tool whenever you need information
from the workspace or need to perform an operation. After receiving tool
results, answer the user concisely and preserve relevant conversation context.
Format code and structured explanations with Markdown when useful.
Keep using tools across multiple steps to make progress, and only give your
final concise answer once the task is complete.
"""

PLAN_MODE_REMINDER = (
    "You are currently in PLAN MODE. You may use ONLY the read-only tools "
    "(read_file, glob, grep) to investigate the codebase. You must NOT write files, "
    "edit files, or run shell commands. Produce a clear, step-by-step plan for the "
    "task, then stop and wait for the user to approve it with /do before doing any "
    "work."
)

EXECUTE_DIRECTIVE = "请按上面的计划开始执行。"

ARK_CODE_LOGO = """\
 █████▓  █████▓  ██  ██▓      █████▓  ██████▓  █████▓   █████▓
██   ██▓ ██  ██▓  ██ ██▓      ██    ▓ ██    ██▓ ██  ██▓  ██    ▓
███████▓ █████▓   ████▓       ██    ▓ ██    ██▓ ██   ██▓ █████▓
██   ██▓ ██  ██▓  ██ ██▓      ██    ▓ ██    ██▓ ██  ██▓  ██    ▓
██   ██▓ ██   ██▓ ██  ██▓      █████▓  ██████▓  █████▓   █████▓"""


def render_banner(version: str, cwd: str) -> Text:
    """渲染包含身份、版本、工作目录和就绪状态的启动横幅。"""

    banner = Text()
    for character in ARK_CODE_LOGO:
        if character == "█":
            banner.append(character, style="bold #00ffff")
        elif character == "▓":
            banner.append(character, style="#008b8b")
        else:
            banner.append(character)
    banner.append(
        f"\nArk Code v{version}\n"
        f"Working directory: {cwd}\n"
        "Ready — send a message to begin."
    )
    return banner
