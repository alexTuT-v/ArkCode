"""权限前四层流水线与三级配置装配。"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..llm import ToolCall
from .blacklist import hits_blacklist
from .rule import RuleSet
from .sandbox import resolve_root, sandbox_ok
from .settings import (
    Settings,
    categorize,
    extract_target,
    friendly_name,
    load_settings,
    to_rule_set,
)
from .types import Category, Decision, Mode, parse_mode


@dataclass
class Engine:
    root: str
    user: RuleSet = field(default_factory=RuleSet)
    project: RuleSet = field(default_factory=RuleSet)
    local: RuleSet = field(default_factory=RuleSet)
    local_path: str = ""
    _start_mode: Mode = Mode.DEFAULT

    def start_mode(self) -> Mode:
        return self._start_mode

    def check(
        self,
        mode: Mode,
        call: ToolCall,
        read_only: bool,
    ) -> tuple[Decision, str]:
        category = categorize(call.name, read_only)
        target, is_file, ok = extract_target(call)
        if call.name == "bash" and target and hits_blacklist(target):
            return Decision.DENY, f"命中危险命令黑名单：{target}"
        if is_file:
            if not ok:
                return Decision.DENY, "无法解析文件路径参数，安全拒绝"
            if not sandbox_ok(self.root, target):
                return Decision.DENY, f"路径在项目目录之外：{target}"
        ask_hit = False
        allow_hit = False
        for rules in (self.local, self.project, self.user):
            decision, hit = rules.match(
                friendly_name(call.name), _relative(self.root, target, is_file)
            )
            if hit and decision is Decision.DENY:
                return (
                    decision,
                    f"匹配 deny 规则：{friendly_name(call.name)}({target})",
                )
            if hit and decision is Decision.ASK:
                ask_hit = True
            elif hit:
                allow_hit = True
        if ask_hit:
            return (
                Decision.ASK,
                f"匹配 ask 规则：{friendly_name(call.name)}({target})",
            )
        if allow_hit:
            return (
                Decision.ALLOW,
                f"匹配 allow 规则：{friendly_name(call.name)}({target})",
            )
        decision = mode_fallback(mode, category)
        if decision is Decision.ASK:
            return decision, f"{mode} 模式下 {category.name.lower()} 类操作需确认"
        return decision, ""

    def persist_local_allow(self, call: ToolCall) -> None:
        from .persist import persist_local_allow

        persist_local_allow(self, call)


def _relative(root: str, target: str, is_file: bool) -> str:
    if not is_file or not target:
        return target
    try:
        path = Path(target)
        if not path.is_absolute():
            return path.as_posix()
        return path.relative_to(root).as_posix()
    except ValueError:
        return Path(target).as_posix()


def mode_fallback(mode: Mode, category: Category) -> Decision:
    if category is Category.READ or mode is Mode.BYPASS:
        return Decision.ALLOW
    if mode is Mode.ACCEPT_EDITS and category is Category.WRITE:
        return Decision.ALLOW
    return Decision.ASK


def _safe_load(path: str) -> Settings:
    try:
        return load_settings(path)
    except Exception:
        return Settings()


def new_engine(root: str) -> tuple[Engine, Exception | None]:
    try:
        resolved = resolve_root(root)
    except Exception as exc:
        fallback = os.path.abspath(os.path.expanduser(root))
        return Engine(
            root=fallback,
            local_path=str(Path(fallback) / ".Arkcode/settings.local.yaml"),
        ), exc

    user_path = str(Path.home() / ".Arkcode/settings.yaml")
    project_path = str(Path(resolved) / ".Arkcode/settings.yaml")
    local_path = str(Path(resolved) / ".Arkcode/settings.local.yaml")
    user_settings = _safe_load(user_path)
    project_settings = _safe_load(project_path)
    local_settings = _safe_load(local_path)
    mode = Mode.DEFAULT
    for settings in (local_settings, project_settings, user_settings):
        parsed, ok = parse_mode(settings.default_mode)
        if ok:
            mode = parsed
            break
    return (
        Engine(
            root=resolved,
            user=to_rule_set(user_settings),
            project=to_rule_set(project_settings),
            local=to_rule_set(local_settings),
            local_path=local_path,
            _start_mode=mode,
        ),
        None,
    )
