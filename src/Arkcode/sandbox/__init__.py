"""OS 级沙箱：限制 Bash 命令的文件写入与网络访问。

macOS 使用 sandbox-exec（Seatbelt），Linux 使用 bubblewrap（bwrap）。
与 permissions/sandbox.py 的路径级检查不同，这里是操作系统层面的强制隔离。
"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SandboxConfig:
    """沙箱配置：可写白名单、强制只读黑名单与网络开关。"""

    allow_write: list[str] = field(default_factory=list)
    deny_write: list[str] = field(default_factory=list)
    network_enabled: bool = False


class Sandbox(ABC):
    """沙箱抽象基类，各平台实现 wrap() 与 available()。"""

    @abstractmethod
    def wrap(self, command: str, config: SandboxConfig) -> str:
        """把原始命令包装为沙箱内执行的命令字符串。"""
        ...

    @abstractmethod
    def available(self) -> bool:
        """检测当前环境是否支持该沙箱。"""
        ...


def create_sandbox() -> Sandbox | None:
    """按操作系统选择沙箱实现；不支持的平台返回 None。"""

    system = platform.system()
    if system == "Darwin":
        from .seatbelt import SeatbeltSandbox

        return SeatbeltSandbox()
    if system == "Linux":
        from .bwrap import BwrapSandbox

        return BwrapSandbox()
    return None
