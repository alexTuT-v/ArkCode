"""ArkCode 命令行入口。"""

import sys

from .config import ConfigError, load
from .tui.app import ArkCodeApp


def main() -> None:
    """加载配置并启动终端界面。"""

    try:
        config = load(".Arkcode/config.yaml")
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None

    try:
        ArkCodeApp(config.providers).run(inline=True, inline_no_clear=True)
    except KeyboardInterrupt:
        return
    except Exception as exc:
        print(f"ArkCode 启动失败: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
