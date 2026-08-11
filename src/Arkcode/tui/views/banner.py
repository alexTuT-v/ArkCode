"""终端启动横幅渲染。"""

from rich.text import Text

from ...prompts.banner import ARK_CODE_LOGO


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
        f"\nArk Code v{version}\nWorking directory: {cwd}\n"
        "Ready — send a message or enter /help for commands."
    )
    return banner
