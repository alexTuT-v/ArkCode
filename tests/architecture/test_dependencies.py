"""领域依赖方向与 composition root 约束守卫。"""

import ast
from pathlib import Path

SOURCE = Path(__file__).parents[2] / "src" / "Arkcode"
DOMAINS = {
    "agents",
    "commands",
    "context",
    "llm",
    "mcp",
    "memory",
    "permissions",
    "prompts",
    "sessions",
    "skills",
    "tools",
}


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    package = ["Arkcode", *path.relative_to(SOURCE).parent.parts]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 0:
                modules.append(node.module)
            else:
                keep = len(package) - (node.level - 1)
                modules.append(".".join([*package[:keep], node.module]))
    return modules


def called_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.append(node.func.attr)
    return names


def test_domains_do_not_import_application_or_tui() -> None:
    failures: list[str] = []
    for domain in sorted(DOMAINS):
        for path in sorted((SOURCE / domain).rglob("*.py")):
            for module in imported_modules(path):
                if module.startswith(("Arkcode.application", "Arkcode.tui")):
                    failures.append(f"{path.relative_to(SOURCE)} -> {module}")
    assert failures == []


def test_tui_does_not_import_concrete_providers() -> None:
    failures = [
        f"{path.relative_to(SOURCE)} -> {module}"
        for path in sorted((SOURCE / "tui").rglob("*.py"))
        for module in imported_modules(path)
        if module.startswith("Arkcode.llm.providers")
    ]
    assert failures == []


def test_concrete_construction_is_confined_to_application() -> None:
    constructors = {
        "MemoryManager",
        "new_default_registry",
        "new_engine",
        "new_manager",
    }
    failures = [
        f"{path.relative_to(SOURCE)} -> {name}"
        for path in sorted(SOURCE.rglob("*.py"))
        if "application" not in path.relative_to(SOURCE).parts
        for name in called_names(path)
        if name in constructors
    ]
    assert failures == []
