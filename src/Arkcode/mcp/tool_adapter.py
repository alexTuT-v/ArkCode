"""把远端 MCP 工具适配为 ArkCode 的统一工具抽象。"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Protocol

import mcp.types as mtypes
from pydantic import BaseModel, ConfigDict, create_model

from Arkcode.tools import Result, Tool

call_timeout: float = 30.0
_VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def _json_type_to_python(json_type: str) -> type:
    mapping: dict[str, type] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    return mapping.get(json_type, str)


def _build_params_model(
    tool_name: str,
    input_schema: dict[str, Any],
) -> type[BaseModel]:
    """从远端 input_schema 动态生成 pydantic 参数模型。"""

    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    field_definitions: dict[str, Any] = {}
    for name, prop in properties.items():
        py_type = _json_type_to_python(prop.get("type", "string"))
        if name in required:
            field_definitions[name] = (py_type, ...)
        else:
            field_definitions[name] = (py_type | None, None)
    # extra="allow"：保留远端 schema 未声明字段，维持原有的全量透传行为。
    return create_model(
        f"{tool_name}Params",
        __config__=ConfigDict(extra="allow"),
        **field_definitions,
    )


def _extract_text(content: list[Any]) -> str:
    """把 MCP 结果内容块文本化，覆盖文本、图片与内嵌资源。"""

    parts: list[str] = []
    for block in content:
        if isinstance(block, mtypes.TextContent):
            parts.append(block.text)
        elif isinstance(block, mtypes.ImageContent):
            parts.append(f"[image: {block.mime_type}]")
        elif isinstance(block, mtypes.EmbeddedResource):
            resource = block.resource
            if hasattr(resource, "text"):
                parts.append(resource.text)
            else:
                parts.append(f"[binary resource: {resource.uri}]")
    return "\n".join(parts) if parts else "(no output)"


class CallerSession(Protocol):
    """McpTool 调用所需的最小会话接口。"""

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> mtypes.CallToolResult: ...


@dataclass
class McpTool(Tool[BaseModel]):
    """一个已绑定远端会话的 MCP 工具。"""

    should_defer = True

    full_name: str
    remote_name: str
    tool_description: str
    input_schema: dict[str, Any]
    _read_only: bool
    caller: CallerSession
    server_name: str = ""
    manager: Any = None
    params_model: type[BaseModel] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.params_model = _build_params_model(self.remote_name, self.input_schema)

    @property
    def read_only(self) -> bool:
        return self._read_only

    def name(self) -> str:
        return self.full_name

    def description(self) -> str:
        return self.tool_description

    def get_schema(self) -> dict[str, Any]:
        """返回远端服务器提供的原始 schema，避免 Pydantic 重新生成丢失约束。"""

        return {
            "name": self.full_name,
            "description": self.tool_description,
            "input_schema": self.input_schema,
        }

    async def execute(self, params: BaseModel) -> Result:
        arguments = params.model_dump(exclude_none=True) or None

        try:
            if self.manager is not None:
                result = await asyncio.wait_for(
                    self.manager.call_server_tool(
                        self.server_name,
                        self.remote_name,
                        arguments,
                    ),
                    timeout=call_timeout,
                )
            else:
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

        remote_is_error = getattr(result, "is_error", None)
        if remote_is_error is None:
            remote_is_error = getattr(result, "isError", False)
        return Result(
            content=_extract_text(result.content),
            is_error=bool(remote_is_error),
        )


def adapt_tool(
    server_name: str,
    remote: mtypes.Tool,
    session: CallerSession,
    manager: Any = None,
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
        server_name=server_name,
        manager=manager,
        caller=session,
    )
