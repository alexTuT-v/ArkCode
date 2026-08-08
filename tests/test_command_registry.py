import pytest

from Arkcode.command import Command, Kind, Registry
from Arkcode.command.ui import NopUI


async def _noop(ui: NopUI, args: str) -> None:
    return None


def command(
    name: str,
    *,
    aliases: list[str] | None = None,
    hidden: bool = False,
) -> Command:
    return Command(
        name, f"{name} description", Kind.LOCAL, _noop, aliases or [], hidden
    )


def test_registry_detects_name_and_alias_conflicts() -> None:
    registry = Registry()
    registry.register(command("help", aliases=["h"]))

    with pytest.raises(RuntimeError, match="help"):
        registry.register(command("help"))
    with pytest.raises(RuntimeError, match="h"):
        registry.register(command("history", aliases=["h"]))
    with pytest.raises(RuntimeError, match="same"):
        Registry().register(command("same", aliases=["same"]))


def test_visible_is_sorted_detached_and_excludes_hidden() -> None:
    registry = Registry()
    registry.register(command("status"))
    registry.register(command("help"))
    registry.register(command("secret", hidden=True))

    visible = registry.visible()
    visible.clear()

    assert [item.name for item in registry.visible()] == ["help", "status"]
    assert registry.lookup("SECRET") is not None


def test_prefix_matches_visible_primary_names_only() -> None:
    registry = Registry()
    registry.register(command("status", aliases=["state"]))
    registry.register(command("session"))
    registry.register(command("help"))

    assert [item.name for item in registry.prefix_match("/s")] == [
        "session",
        "status",
    ]
    assert registry.prefix_match("/state") == []
    assert registry.prefix_match("/description") == []


def test_register_replace_removes_old_name_aliases_and_visible_entry() -> None:
    registry = Registry()
    old = command("review", aliases=["r"])
    replacement = command("review", aliases=["inspect"])
    registry.register(old)

    registry.register(replacement, replace=True)

    assert registry.lookup("review") is replacement
    assert registry.lookup("r") is None
    assert registry.lookup("inspect") is replacement
    assert registry.visible() == [replacement]


def test_clear_removes_all_command_indexes() -> None:
    registry = Registry()
    registry.register(command("help", aliases=["h"]))
    registry.register(command("secret", hidden=True))

    registry.clear()

    assert registry.lookup("help") is None
    assert registry.lookup("h") is None
    assert registry.visible() == []
    assert registry.prefix_match("") == []
