"""权限设置 pydantic 化宽容行为测试。"""

from pathlib import Path

from Arkcode.permissions.settings import load_settings


def test_settings_ignores_non_string_permission_items(tmp_path: Path) -> None:
    path = tmp_path / "permissions.yaml"
    path.write_text(
        "default_mode: default\npermissions:\n  allow:\n    - read_file\n    - 123\n",
        encoding="utf-8",
    )

    settings = load_settings(str(path))

    assert settings.permissions.allow == ["read_file"]
    assert settings.default_mode == "default"
