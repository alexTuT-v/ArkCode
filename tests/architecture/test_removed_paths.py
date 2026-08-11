"""旧单数包路径移除断言。"""

from pathlib import Path


def test_old_source_packages_are_removed() -> None:
    root = Path(__file__).parents[2] / "src" / "Arkcode"
    for name in (
        "agent",
        "command",
        "compact",
        "permission",
        "prompt",
        "session",
        "tool",
    ):
        assert not (root / name).exists(), name
