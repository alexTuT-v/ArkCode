"""ArkCode 命令行入口。"""

import argparse
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


def _parse_team_member_args() -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--team-member", action="store_true")
    parser.add_argument("--team")
    parser.add_argument("--member")
    parser.add_argument("--agent-id")
    parser.add_argument("--session-dir")
    parser.add_argument("--worktree")
    parser.add_argument("--agent-type")
    parser.add_argument("--model")
    parser.add_argument("--plan-mode", action="store_true")
    try:
        args, _ = parser.parse_known_args(sys.argv[1:])
    except SystemExit:
        return None
    return args


def main() -> None:
    """加载配置并启动终端界面。"""

    if "--team-member" in sys.argv[1:]:
        args = _parse_team_member_args()
        if args is None:
            raise SystemExit(2)
        from ..teams.worker import run_team_member

        raise SystemExit(asyncio.run(run_team_member(args)))

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
