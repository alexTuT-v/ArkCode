"""ArkCode 命令行入口。"""

import asyncio
import sys
from pathlib import Path

from . import __version__
from . import mcp as mcp_client
from .config import ConfigError, load
from .permission import new_engine
from .tool import new_default_registry
from .tui.app import new_app


async def _amain() -> int:
    """在同一个事件循环中维持 MCP 会话和终端界面。"""

    config = load(".env")
    root = str(Path.cwd().resolve())
    registry = new_default_registry()
    mcp_config = mcp_client.load_config(root)
    manager = await mcp_client.new_manager(mcp_config, version=__version__)

    try:
        for remote_tool in manager.tools():
            registry.register(remote_tool)
        engine, error = new_engine(root)
        if error is not None:
            print(f"权限引擎降级: {error}", file=sys.stderr)
        await new_app(
            config.providers,
            __version__,
            registry,
            engine,
            mcp_status=manager.status(),
        ).run_async()
    finally:
        await manager.close()
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
