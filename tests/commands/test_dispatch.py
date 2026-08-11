"""Slash 输入解析测试。"""

import pytest

from Arkcode.commands import parse


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ("", "", False)),
        ("   ", ("", "", False)),
        ("hello", ("", "", False)),
        ("/", ("", "", True)),
        ("/help", ("help", "", True)),
        ("  /HELP  ", ("help", "", True)),
        ("/help xx", ("help", "xx", True)),
        ("/skill   info review ", ("skill", "info review", True)),
        ("/help  ", ("help", "", True)),
        ("//double", ("/double", "", True)),
        ("/ /help", ("", "/help", True)),
    ],
)
def test_parse_slash_commands(
    value: str,
    expected: tuple[str, str, bool],
) -> None:
    assert parse(value) == expected
