"""MCP server 配置加载、合并与校验。"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from dataclasses import field as dfield
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ServerConfig(BaseModel):
    """一个已经完成变量展开和字段校验的 MCP server。"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    type: Literal["stdio", "http"]
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)


class Config(BaseModel):
    """归一化后的 MCP 配置。"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    servers: dict[str, ServerConfig] = Field(default_factory=dict)


@dataclass
class _RawServer:
    type: Any = None
    command: Any = ""
    args: Any = dfield(default_factory=list)
    env: Any = dfield(default_factory=dict)
    url: Any = ""
    headers: Any = dfield(default_factory=dict)


def _warn(message: str) -> None:
    print(f"[mcp] warn: {message}", file=sys.stderr)


def _load_file(path: Path) -> dict[str, _RawServer]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError("top level must be a mapping")
        section = data.get("mcp_servers")
        if section is None:
            return {}
        if not isinstance(section, dict):
            raise ValueError("mcp_servers must be a mapping")

        servers: dict[str, _RawServer] = {}
        for name, definition in section.items():
            if not isinstance(name, str) or not isinstance(definition, dict):
                _warn(f"skip server {name}: definition must be a mapping")
                continue
            servers[name] = _RawServer(
                type=definition.get("type"),
                command=definition.get("command", ""),
                args=definition.get("args", []),
                env=definition.get("env", {}),
                url=definition.get("url", ""),
                headers=definition.get("headers", {}),
            )
        return servers
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
        # 不回显异常详情，避免 YAML 解析错误把凭据所在行带到日志。
        _warn(f"load {path} failed: {type(exc).__name__}")
        return {}


def _expand_vars(value: str) -> tuple[str, list[str]]:
    undefined: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            undefined.append(name)
            return ""
        return os.environ[name]

    return _ENV_PATTERN.sub(replace, value), undefined


def _apply_expansion(name: str, server: _RawServer) -> None:
    missing: set[str] = set()
    for mapping_name in ("env", "headers"):
        mapping = getattr(server, mapping_name)
        if not isinstance(mapping, dict):
            continue
        expanded: dict[Any, Any] = {}
        for key, value in mapping.items():
            if not isinstance(value, str):
                expanded[key] = value
                continue
            expanded_value, undefined = _expand_vars(value)
            expanded[key] = expanded_value
            missing.update(undefined)
        setattr(server, mapping_name, expanded)
    for variable in sorted(missing):
        _warn(f"undefined env var ${{{variable}}} referenced by server {name}")


def _merge_servers(
    user: dict[str, _RawServer], project: dict[str, _RawServer]
) -> dict[str, _RawServer]:
    merged = dict(user)
    merged.update(project)
    return merged


def _is_string_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    )


def _validate_server(name: str, server: _RawServer) -> ServerConfig | None:
    if server.type not in ("stdio", "http"):
        _warn(f"skip server {name}: type must be stdio or http")
        return None
    if not isinstance(server.args, list) or not all(
        isinstance(arg, str) for arg in server.args
    ):
        _warn(f"skip server {name}: args must be a string array")
        return None
    if not _is_string_map(server.env):
        _warn(f"skip server {name}: env must be a string map")
        return None
    if not _is_string_map(server.headers):
        _warn(f"skip server {name}: headers must be a string map")
        return None
    if server.type == "stdio" and (
        not isinstance(server.command, str) or not server.command
    ):
        _warn(f"skip server {name}: stdio command is required")
        return None
    if server.type == "http" and (not isinstance(server.url, str) or not server.url):
        _warn(f"skip server {name}: http url is required")
        return None

    return ServerConfig(
        type=server.type,
        command=server.command if isinstance(server.command, str) else "",
        args=list(server.args),
        env=dict(server.env),
        url=server.url if isinstance(server.url, str) else "",
        headers=dict(server.headers),
    )


def load_config(root: str) -> Config:
    """加载用户级与项目级配置；任何坏配置都只降级为空。"""

    try:
        try:
            user_path = Path.home() / ".Arkcode" / "config.yaml"
            user = _load_file(user_path)
        except Exception as exc:
            _warn(f"load user config failed: {type(exc).__name__}")
            user = {}

        project = _load_file(Path(root) / ".Arkcode" / "settings.yaml")
        for name, server in [*user.items(), *project.items()]:
            _apply_expansion(name, server)

        valid: dict[str, ServerConfig] = {}
        for name, server in _merge_servers(user, project).items():
            normalized = _validate_server(name, server)
            if normalized is not None:
                valid[name] = normalized
        return Config(servers=valid)
    except Exception as exc:
        _warn(f"load config failed: {type(exc).__name__}")
        return Config()
