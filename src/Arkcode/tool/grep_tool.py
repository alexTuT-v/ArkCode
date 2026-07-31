"""使用 Python 正则搜索文件内容。"""

import asyncio
import json
import multiprocessing
import re
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

from .base import Result, Tool
from .utils import truncate

_MAX_SEARCHED_LINE_CHARS = 1_000_000
_MAX_DISPLAY_LINE_CHARS = 2_000


def _search_file(
    path: Path,
    regex: re.Pattern[str],
    limit: int,
) -> list[str]:
    """在 worker 中搜索单个文件，并限制单行读取与展示体量。"""

    matches: list[str] = []
    with path.open(errors="replace") as handle:
        line_number = 0
        while True:
            line = handle.readline(_MAX_SEARCHED_LINE_CHARS + 1)
            if not line:
                break
            line_number += 1
            line_too_long = len(line) > _MAX_SEARCHED_LINE_CHARS
            searched = line[:_MAX_SEARCHED_LINE_CHARS]
            if line_too_long and not line.endswith("\n"):
                while line and not line.endswith("\n"):
                    line = handle.readline(_MAX_SEARCHED_LINE_CHARS + 1)
            if not regex.search(searched):
                continue
            displayed = searched.rstrip()[:_MAX_DISPLAY_LINE_CHARS]
            if line_too_long:
                displayed += " [line truncated; remainder not searched]"
            matches.append(f"{path}:{line_number}:{displayed}")
            if len(matches) >= limit:
                break
    return matches


def _grep_worker(
    path_value: str,
    pattern: str,
    file_glob: str | None,
    connection: Any,
) -> None:
    """在隔离进程内完成遍历与正则搜索。"""

    try:
        root = Path(path_value)
        regex = re.compile(pattern)
        files = [root] if root.is_file() else root.rglob(file_glob or "*")
        matches: list[str] = []
        truncated = False
        for path in files:
            if not path.is_file():
                continue
            try:
                file_matches = _search_file(
                    path,
                    regex,
                    101 - len(matches),
                )
            except OSError:
                continue
            matches.extend(file_matches)
            if len(matches) > 100:
                matches = matches[:100]
                truncated = True
                break
        if not matches:
            connection.send(("无命中", False))
            return
        content = truncate(
            "\n".join(matches),
            max_lines=100,
            max_chars=30_000,
        )
        if truncated:
            content = content.rstrip()
            if not content.endswith("[truncated]"):
                content += "\n[truncated]"
        connection.send((content, False))
    except Exception as exc:
        connection.send((f"grep 搜索失败: {exc}", True))
    finally:
        connection.close()


async def _stop_worker(process: BaseProcess) -> None:
    if process.is_alive():
        process.terminate()
    await asyncio.to_thread(process.join, 1.0)
    if process.is_alive():
        process.kill()
        await asyncio.to_thread(process.join)


async def _search_in_subprocess(
    path_value: str,
    pattern: str,
    file_glob: str | None,
) -> Result:
    """在可终止子进程内搜索，使外层超时能停止实际工作。"""

    context = multiprocessing.get_context("spawn")
    receive_connection, send_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_grep_worker,
        args=(path_value, pattern, file_glob, send_connection),
        name="ArkCodeGrep",
    )
    process.start()
    send_connection.close()
    try:
        try:
            content, is_error = await asyncio.to_thread(receive_connection.recv)
        except EOFError:
            return Result("grep 工作进程异常退出", is_error=True)
        await asyncio.to_thread(process.join, 1.0)
        if process.is_alive():
            await _stop_worker(process)
            return Result("grep 工作进程未正常结束", is_error=True)
        return Result(content, is_error=is_error)
    except asyncio.CancelledError:
        await _stop_worker(process)
        raise
    finally:
        receive_connection.close()


class GrepTool(Tool):
    """搜索文件内容并返回文件、行号与命中行。"""

    read_only = True

    def name(self) -> str:
        return "grep"

    def description(self) -> str:
        return "用 Python 正则搜索文件内容，最多返回 100 条命中。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python 正则表达式"},
                "path": {"type": "string", "description": "搜索根目录或文件"},
                "glob": {"type": "string", "description": "可选文件名 glob"},
            },
            "required": ["pattern"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(f"参数 JSON 无效: {exc}", is_error=True)
        if not isinstance(data, dict):
            return Result("参数必须是 JSON 对象", is_error=True)
        pattern = data.get("pattern")
        root_value = data.get("path") or "."
        file_glob = data.get("glob")
        if not isinstance(pattern, str) or not pattern:
            return Result("缺少必填参数 pattern", is_error=True)
        if not isinstance(root_value, str):
            return Result("参数 path 必须是字符串", is_error=True)
        if file_glob is not None and not isinstance(file_glob, str):
            return Result("参数 glob 必须是字符串", is_error=True)
        try:
            re.compile(pattern)
        except re.error as exc:
            return Result(f"正则非法: {exc}", is_error=True)

        root = Path(root_value)
        if not root.exists():
            return Result(f"搜索路径不存在: {root}", is_error=True)
        return await _search_in_subprocess(root_value, pattern, file_glob)
