"""Catalog 三层加载与覆盖测试。"""

from pathlib import Path

import pytest

from Arkcode.subagents.catalog import Catalog
from Arkcode.subagents.models import Source


def _write_definition(directory: Path, name: str, *, extra: str = "") -> None:
    agents_dir = directory / ".Arkcode" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: 角色 {name}{extra}\n---\n正文",
        encoding="utf-8",
    )


def test_catalog_loads_three_builtin_roles(tmp_path: Path) -> None:
    catalog = Catalog(project_root=tmp_path, user_root=tmp_path)
    catalog.load()
    names = {definition.name for definition in catalog._definitions.values()}
    assert {"general-purpose", "explore", "plan"} <= names
    for name in ("general-purpose", "explore", "plan"):
        assert name.islower()
        assert catalog.resolve(name) is not None


def test_catalog_project_overrides_builtin_and_user(tmp_path: Path) -> None:
    project = tmp_path / "project"
    user = tmp_path / "user"
    _write_definition(user, "explore", extra=", user 版")
    _write_definition(project, "explore", extra=", project 版")
    catalog = Catalog(project_root=project, user_root=user)
    catalog.load()
    resolved = catalog.resolve("explore")
    assert resolved is not None
    assert resolved.source is Source.PROJECT
    assert "project 版" in resolved.description


def test_catalog_user_warning_and_skip_on_bad_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    user = tmp_path / "user"
    _write_definition(user, "good")
    agents_dir = user / ".Arkcode" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "bad.md").write_text("---\nname: Bad Name\n---\n", encoding="utf-8")
    catalog = Catalog(project_root=tmp_path, user_root=user)
    catalog.load()
    assert catalog.resolve("good") is not None
    assert catalog.resolve("bad") is None
    assert any("跳过 Agent 定义" in warning for warning in catalog.warnings)
    assert "bad.md" in capsys.readouterr().err


def test_catalog_plugin_layer_is_empty(tmp_path: Path) -> None:
    catalog = Catalog(project_root=tmp_path, user_root=tmp_path)
    catalog.load()
    assert all(
        definition.source is not Source.PLUGIN
        for definition in catalog._definitions.values()
    )


def test_catalog_reload_reflects_new_files(tmp_path: Path) -> None:
    catalog = Catalog(project_root=tmp_path, user_root=tmp_path)
    catalog.load()
    assert catalog.resolve("fresh") is None
    _write_definition(tmp_path, "fresh")
    catalog.reload()
    assert catalog.resolve("fresh") is not None
