"""ExecutionPathContext：显式 cwd 与路径 containment 的共享上下文。"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Access(StrEnum):
    READ = "read"
    WRITE = "write"


class PathPermissionError(PermissionError):
    """路径越界或被声明为只读目标。"""


@dataclass(frozen=True, slots=True)
class ExecutionPathContext:
    """一次 Agent 执行的路径边界。"""

    cwd: Path
    workspace_root: Path
    readonly_shared_targets: tuple[Path, ...] = ()

    @classmethod
    def at(cls, root: str | Path) -> ExecutionPathContext:
        resolved = Path(root).resolve()
        return cls(cwd=resolved, workspace_root=resolved)


_workspace_context: contextvars.ContextVar[ExecutionPathContext] = (
    contextvars.ContextVar("arkcode_workspace_context")
)


def current_workspace() -> ExecutionPathContext:
    """读取当前路径上下文；无上下文时以进程 cwd 为默认边界。"""

    try:
        return _workspace_context.get()
    except LookupError:
        return ExecutionPathContext.at(Path.cwd())


@contextmanager
def workspace_scope(context: ExecutionPathContext) -> Iterator[None]:
    token = _workspace_context.set(context)
    try:
        yield
    finally:
        try:
            _workspace_context.reset(token)
        except ValueError:
            pass


def _inside(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_path(value: str, access: Access) -> Path:
    """按当前 cwd 解析路径，做 realpath containment 校验。"""

    context = current_workspace()
    path = Path(value)
    if not path.is_absolute():
        path = context.cwd / path
    try:
        real = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise PathPermissionError(f"无法解析路径 {path}: {exc}") from exc
    root = context.workspace_root.resolve()
    if _inside(root, real):
        return real
    for target in context.readonly_shared_targets:
        resolved_target = target.resolve()
        if _inside(resolved_target, real):
            if access is Access.WRITE:
                raise PathPermissionError(
                    f"路径 {real} 位于只读共享目录 {resolved_target}，拒绝写入"
                )
            return real
    raise PathPermissionError(f"路径 {real} 在 workspace 之外，拒绝访问")
