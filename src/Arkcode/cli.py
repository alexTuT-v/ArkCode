"""ArkCode 命令行入口。"""

import sys

from .config import ConfigError, load
from .tui.app import ArkCodeApp


def main() -> None:
    """加载配置并启动终端界面。"""

    try:
        config = load(".env")
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None

    try:
        ArkCodeApp(config.providers).run()
    except KeyboardInterrupt:
        return
    except Exception:
        print("ArkCode 启动失败，请检查配置或终端环境", file=sys.stderr)
        raise SystemExit(1) from None
