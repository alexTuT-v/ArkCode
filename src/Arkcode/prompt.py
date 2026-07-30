"""应用内置提示词与启动横幅。"""

SYSTEM_PROMPT = """\
You are ArkCode, a precise and helpful AI coding assistant.
Answer the user directly, preserve relevant conversation context, and format
code and structured explanations with Markdown when useful.
"""

ARK_CODE_LOGO = """\
 █████▓  █████▓  ██  ██▓      █████▓  ██████▓  █████▓   █████▓
██   ██▓ ██  ██▓  ██ ██▓      ██    ▓ ██    ██▓ ██  ██▓  ██    ▓
███████▓ █████▓   ████▓       ██    ▓ ██    ██▓ ██   ██▓ █████▓
██   ██▓ ██  ██▓  ██ ██▓      ██    ▓ ██    ██▓ ██  ██▓  ██    ▓
██   ██▓ ██   ██▓ ██  ██▓      █████▓  ██████▓  █████▓   █████▓"""


def render_banner(version: str, cwd: str) -> str:
    """渲染包含身份、版本、工作目录和就绪状态的启动横幅。"""

    return (
        f"{ARK_CODE_LOGO}\n"
        f"Ark Code v{version}\n"
        f"Working directory: {cwd}\n"
        "Ready — send a message to begin."
    )
