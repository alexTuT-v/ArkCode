"""ArkCode 命令行入口。"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

from . import __version__
from . import mcp as mcp_client
from .agent import SessionRuntime
from .compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from .config import ConfigError, load
from .instructions import Loader
from .memory import Manager as MemoryManager
from .permission import new_engine
from .session import Writer, clean_expired
from .tool import new_default_registry
from .tui.app import new_app


async def _amain() -> int:
    """在同一个事件循环中维持 MCP 会话和终端界面。"""

    config = load(".env")
    root = str(Path.cwd().resolve())
    instruction_text = Loader(root).load()
    memory_manager = MemoryManager(
        str(Path(root) / ".Arkcode" / "memory"),
        str(Path.home() / ".Arkcode" / "memory"),
        None,
        "",
    )
    memory_text = memory_manager.load_index()
    registry = new_default_registry()
    mcp_config = mcp_client.load_config(root)
    mcp_manager = await mcp_client.new_manager(mcp_config, version=__version__)
    writer: Writer | None = None
    cleanup_task: asyncio.Task[None] | None = None

    try:
        for remote_tool in mcp_manager.tools():
            registry.register(remote_tool)
        engine, error = new_engine(root)
        if error is not None:
            print(f"权限引擎降级: {error}", file=sys.stderr)
        runtime = SessionRuntime(
            replacement=ContentReplacementState(),
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context(root),
        )
        writer = Writer(runtime.session.session_dir)
        sessions_dir = str(Path(root) / ".Arkcode" / "sessions")
        cleanup_task = asyncio.create_task(
            asyncio.to_thread(clean_expired, sessions_dir, timedelta(days=30))
        )
        app = new_app(
            config.providers,
            __version__,
            registry,
            engine,
            mcp_status=mcp_manager.status(),
            runtime=runtime,
            writer=writer,
            mem_mgr=memory_manager,
            instruction_text=instruction_text,
            memory_text=memory_text,
            sessions_dir=sessions_dir,
            workspace=root,
        )
        await app.run_async()
    finally:
        if writer is not None:
            writer.close()
        if cleanup_task is not None:
            await cleanup_task
        await mcp_manager.close()
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
