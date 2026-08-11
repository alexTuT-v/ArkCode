"""创建后三步 best-effort 设置；明确跳过 Git hooks。"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from .git import GitRunner
from .models import WorktreeConfig, WorktreeConfigError


def load_worktree_config(repo_root: str | Path) -> WorktreeConfig:
    """读取 .Arkcode/worktree.yaml；shared_writable_dirs 非空即拒绝。"""

    path = Path(repo_root) / ".Arkcode" / "worktree.yaml"
    if not path.is_file():
        return WorktreeConfig()
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise WorktreeConfigError(f"worktree 配置读取失败: {exc}") from exc
    if not isinstance(value, dict):
        raise WorktreeConfigError("worktree 配置必须是 YAML 对象")
    readonly = value.get("shared_readonly_dirs", ["node_modules", ".venv", "vendor"])
    writable = value.get("shared_writable_dirs", [])
    if not isinstance(readonly, list) or not all(
        isinstance(item, str) for item in readonly
    ):
        raise WorktreeConfigError("shared_readonly_dirs 必须是字符串数组")
    if not isinstance(writable, list) or not all(
        isinstance(item, str) for item in writable
    ):
        raise WorktreeConfigError("shared_writable_dirs 必须是字符串数组")
    if writable:
        raise WorktreeConfigError(
            "shared_writable_dirs 非空：本期不支持可写共享目录，避免伪隔离"
        )
    return WorktreeConfig(
        shared_readonly_dirs=tuple(readonly),
        shared_writable_dirs=(),
    )


def _copy_config_files(repo_root: Path, wt_path: Path) -> None:
    for relative in ("config.yaml", "settings.local.yaml"):
        source = repo_root / ".Arkcode" / relative
        target = wt_path / ".Arkcode" / relative
        if not source.is_file() or target.exists():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        except OSError as exc:
            print(f"警告: 复制 {relative} 失败: {exc}", file=sys.stderr)


def _create_readonly_symlinks(
    repo_root: Path,
    wt_path: Path,
    config: WorktreeConfig,
    *,
    readonly_guaranteed: bool,
) -> None:
    if not readonly_guaranteed:
        print(
            "警告: 无法保证共享目录只读，跳过 readonly symlink 设置",
            file=sys.stderr,
        )
        return
    for name in config.shared_readonly_dirs:
        source = repo_root / name
        target = wt_path / name
        if not source.is_dir() or target.exists():
            continue
        try:
            target.symlink_to(source, target_is_directory=True)
        except OSError as exc:
            print(f"警告: 建立共享目录 {name} symlink 失败: {exc}", file=sys.stderr)


async def _copy_worktreeinclude(
    repo_root: Path,
    wt_path: Path,
    runner: GitRunner,
) -> None:
    include_file = repo_root / ".worktreeinclude"
    if not include_file.is_file():
        return
    patterns = [
        line.strip()
        for line in include_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not patterns:
        return
    result = await runner.run(
        [
            "-C",
            str(repo_root),
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--directory",
        ],
        cwd=repo_root,
    )
    if not result.ok:
        print("警告: 无法枚举被忽略文件，跳过 .worktreeinclude", file=sys.stderr)
        return
    ignored = [line for line in result.stdout.splitlines() if line.strip()]
    import fnmatch

    for relative in ignored:
        if not any(fnmatch.fnmatch(relative, pattern) for pattern in patterns):
            continue
        source = repo_root / relative
        target = wt_path / relative
        if not source.is_file() or target.exists():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        except OSError as exc:
            print(f"警告: 复制 ignored 文件 {relative} 失败: {exc}", file=sys.stderr)


async def perform_post_creation_setup(
    repo_root: str | Path,
    wt_path: str | Path,
    runner: GitRunner,
    *,
    readonly_guaranteed: bool,
) -> None:
    """三个独立 best-effort 步骤，任何失败只警告不中断。"""

    root = Path(repo_root).resolve()
    target = Path(wt_path).resolve()
    config = load_worktree_config(root)
    _copy_config_files(root, target)
    _create_readonly_symlinks(
        root,
        target,
        config,
        readonly_guaranteed=readonly_guaranteed,
    )
    await _copy_worktreeinclude(root, target, runner)
