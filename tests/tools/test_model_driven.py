"""工具层模型驱动的基础契约测试。"""

import json

import pytest

from Arkcode.tools import new_default_registry


def test_read_file_schema_comes_from_model() -> None:
    registry = new_default_registry()
    schema = registry.get("read_file").get_schema()
    assert schema["name"] == "read_file"
    assert (
        schema["input_schema"]["properties"]["path"]["description"]
        == "要读取的文件路径"
    )
    assert schema["input_schema"]["required"] == ["path"]


@pytest.mark.asyncio
async def test_registry_validation_error_is_classified() -> None:
    registry = new_default_registry()

    result = await registry.execute("read_file", '{"path": 123}')

    assert result.is_error is True
    assert "参数校验失败" in result.content


@pytest.mark.asyncio
async def test_glob_and_grep_validate_parameters() -> None:
    registry = new_default_registry()

    missing = await registry.execute("grep", '{"pattern": 1}')
    assert missing.is_error is True
    assert "参数校验失败" in missing.content


@pytest.mark.asyncio
async def test_write_and_edit_require_fields(tmp_path) -> None:
    registry = new_default_registry()
    target = tmp_path / "out.txt"

    missing_content = await registry.execute(
        "write_file",
        json.dumps({"path": str(target)}),
    )
    assert missing_content.is_error is True
    assert "参数校验失败" in missing_content.content

    missing_old = await registry.execute(
        "edit_file",
        json.dumps({"path": str(target), "old_string": "x"}),
    )
    assert missing_old.is_error is True


@pytest.mark.asyncio
async def test_bash_requires_command() -> None:
    registry = new_default_registry()

    result = await registry.execute("bash", "{}")

    assert result.is_error is True
    assert "参数校验失败" in result.content
