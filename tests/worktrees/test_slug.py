"""slug 校验测试。"""

import pytest

from Arkcode.worktrees import flatten_slug, validate_slug


def test_valid_slug_accepted() -> None:
    validate_slug("feature/a")
    validate_slug("alice")
    validate_slug("team.alice_v1-x")


@pytest.mark.parametrize(
    "bad",
    ["../etc", "..", ".", "a//b", "a/b ", "/a", "a/", "a b", "a*b", "x" * 65],
)
def test_invalid_slug_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_slug(bad)


def test_flatten_slug() -> None:
    assert flatten_slug("team/alice") == "team+alice"
    assert flatten_slug("alice") == "alice"
