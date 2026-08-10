"""ArkCode 命令行入口。"""

import asyncio
import sys
from pathlib import Path

from .. import __version__
from ..config import ConfigError
from ..tui.app import new_app
from .bootstrap import build_runtime


async def _amain() -> int:
    """在同一个事件循环中维持 MCP 会话和终端界面。"""

    runtime = await build_runtime(Path.cwd(), __version__)
    app = new_app(runtime)
    try:
        await app.run_async()
    finally:
        await runtime.shutdown()
    return 0


def main() -> None:
    """加载配置并启动终端界面。"""

    if "--version" in sys.argv[1:]:
        print(__version__)
        return

    try:
        asyncio.run(_amain())
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        return
    except Exception:
        print("ArkCode 启动失败，请检查配置或终端环境", file=sys.stderr)
        raise SystemExit(1) from None
