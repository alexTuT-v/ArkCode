"""把远端 MCP 工具适配为 ArkCode 的统一工具抽象。"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Protocol

import mcp.types as mtypes

from Arkcode.tool import Result, Tool

call_timeout: float = 30.0
_VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_non_text_warn_once: set[str] = set()


class CallerSession(Protocol):
    """McpTool 调用所需的最小会话接口。"""

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> mtypes.CallToolResult: ...


@dataclass
class McpTool(Tool):
    """一个已绑定远端会话的 MCP 工具。"""

    full_name: str
    remote_name: str
    tool_description: str
    input_schema: dict[str, Any]
    _read_only: bool
    caller: CallerSession

    @property
    def read_only(self) -> bool:
        return self._read_only

    def name(self) -> str:
        return self.full_name

    def description(self) -> str:
        return self.tool_description

    def parameters(self) -> dict[str, Any]:
        return dict(self.input_schema)

    async def execute(self, args: str) -> Result:
        try:
            decoded = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(content=f"MCP 工具参数 JSON 无效: {exc}", is_error=True)
        if not isinstance(decoded, dict):
            return Result(content="MCP 工具参数 JSON 必须是对象", is_error=True)
        arguments = decoded or None

        try:
            result = await asyncio.wait_for(
                self.caller.call_tool(self.remote_name, arguments),
                timeout=call_timeout,
            )
        except TimeoutError:
            return Result(
                content=f"MCP 工具调用超时 ({call_timeout:g}s)", is_error=True
            )
        except Exception as exc:
            return Result(content=f"MCP 工具调用失败: {exc}", is_error=True)

        texts: list[str] = []
        dropped_non_text = False
        for block in result.content:
            if isinstance(block, mtypes.TextContent):
                texts.append(block.text)
            else:
                dropped_non_text = True
        if dropped_non_text and self.full_name not in _non_text_warn_once:
            _non_text_warn_once.add(self.full_name)
            print(
                f"[mcp] warn: tool {self.full_name} returned non-text content "
                "blocks (dropped)",
                file=sys.stderr,
            )
        remote_is_error = getattr(result, "is_error", None)
        if remote_is_error is None:
            remote_is_error = getattr(result, "isError", False)
        return Result(content="\n".join(texts), is_error=bool(remote_is_error))


def adapt_tool(
    server_name: str, remote: mtypes.Tool, session: CallerSession
) -> McpTool | None:
    """构造带命名空间的工具；非法模型工具名会被安全跳过。"""

    full_name = f"mcp__{server_name}__{remote.name}"
    if _VALID_NAME.fullmatch(full_name) is None:
        print(
            f"[mcp] warn: skip tool {full_name}: name contains illegal characters",
            file=sys.stderr,
        )
        return None
    remote_schema = getattr(remote, "input_schema", None)
    if remote_schema is None:
        remote_schema = getattr(remote, "inputSchema", None)
    schema = dict(remote_schema) if remote_schema else {"type": "object"}
    annotations = remote.annotations
    read_only_hint = getattr(annotations, "read_only_hint", None)
    if annotations is not None and read_only_hint is None:
        read_only_hint = getattr(annotations, "readOnlyHint", None)
    return McpTool(
        full_name=full_name,
        remote_name=remote.name,
        tool_description=remote.description
        or f"来自 MCP server {server_name} 的工具 {remote.name}",
        input_schema=schema,
        _read_only=read_only_hint is True,
        caller=session,
    )
