"""项目根路径沙箱与符号链接防逃逸。"""

from pathlib import Path


def resolve_root(root: str) -> str:
    return str(Path(root).expanduser().resolve(strict=True))


def eval_symlinks_or_ancestor(abs_path: str) -> str:
    candidate = Path(abs_path)
    missing: list[str] = []
    while not candidate.exists():
        if candidate == candidate.parent:
            raise FileNotFoundError(abs_path)
        missing.append(candidate.name)
        candidate = candidate.parent
    resolved = candidate.resolve(strict=True)
    for part in reversed(missing):
        resolved /= part
    return str(resolved)


def sandbox_ok(root: str, path: str) -> bool:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(root) / candidate
    try:
        resolved = Path(eval_symlinks_or_ancestor(str(candidate)))
        root_path = Path(root)
        return resolved == root_path or root_path in resolved.parents
    except (OSError, RuntimeError):
        return False
