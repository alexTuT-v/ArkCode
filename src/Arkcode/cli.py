"""ArkCode 命令行入口。"""

import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, load
from .permission import new_engine
from .tool import new_default_registry
from .tui.app import new_app


def main() -> None:
    """加载配置并启动终端界面。"""

    if "--version" in sys.argv[1:]:
        print(__version__)
        return

    try:
        config = load(".env")
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None

    try:
        engine, error = new_engine(str(Path.cwd().resolve()))
        if error is not None:
            print(f"权限引擎降级: {error}", file=sys.stderr)
        new_app(
            config.providers,
            __version__,
            new_default_registry(),
            engine,
        ).run()
    except KeyboardInterrupt:
        return
    except Exception:
        print("ArkCode 启动失败，请检查配置或终端环境", file=sys.stderr)
        raise SystemExit(1) from None
