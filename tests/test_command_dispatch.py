import pytest

from Arkcode.command import parse


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ("", False)),
        ("   ", ("", False)),
        ("hello", ("", False)),
        ("/", ("", True)),
        ("/help", ("help", True)),
        ("  /HELP  ", ("help", True)),
        ("/help xx", ("", True)),
        ("/help  ", ("help", True)),
        ("//double", ("/double", True)),
        ("/ /help", ("", True)),
    ],
)
def test_parse_slash_commands(value: str, expected: tuple[str, bool]) -> None:
    assert parse(value) == expected
