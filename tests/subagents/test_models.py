"""SubAgent 模型、身份与解析器测试。"""

from pathlib import Path

import pytest

from Arkcode.agents.identity import AgentIdentity, current_identity, identity_scope
from Arkcode.subagents.models import Source
from Arkcode.subagents.parser import (
    DefinitionParseError,
    parse_definition,
    parse_definition_file,
)


@pytest.mark.parametrize(
    "source",
    ["main", "defined", "fork", "skill", "teammate"],
)
def test_identity_all_sources_constructible(source: str) -> None:
    identity = AgentIdentity(
        agent_id="agent-1",
        parent_id="lead",
        trace_id="trace-1",
        agent_type="explore",
        name="explore",
        source=source,  # type: ignore[arg-type]
    )
    assert identity.source == source


def test_identity_contextvar_nesting_restores() -> None:
    base = AgentIdentity.main()
    child = AgentIdentity(
        agent_id="agent-1",
        parent_id="lead",
        trace_id="trace-1",
        agent_type="explore",
        name="explore",
        source="defined",
    )
    with identity_scope(base):
        assert current_identity() == base
        with identity_scope(child):
            assert current_identity() == child
        assert current_identity() == base
    assert current_identity().agent_id == "lead"


def _definition_text(name: str, **extra: object) -> str:
    fields = {
        "name": name,
        "description": "测试角色",
        **extra,
    }
    frontmatter = "\n".join(f"{key}: {value}" for key, value in fields.items())
    return f"---\n{frontmatter}\n---\n正文指令"


def test_definition_parser_accepts_explore_v2() -> None:
    definition = parse_definition(
        _definition_text("explore-v2", tools="[read_file, glob]"),
    )
    assert definition.name == "explore-v2"
    assert definition.tools == ("read_file", "glob")
    assert definition.instructions_content == "正文指令"


@pytest.mark.parametrize("bad_name", ["Explore", "foo_bar", "foo bar", "x" * 33])
def test_definition_parser_rejects_invalid_names(bad_name: str) -> None:
    with pytest.raises(DefinitionParseError):
        parse_definition(_definition_text(bad_name))


def test_definition_parser_full_fields() -> None:
    definition = parse_definition(
        _definition_text(
            "worker",
            disallowedTools="[write_file]",
            model="sonnet",
            maxTurns=12,
            permissionMode="dontAsk",
            background="true",
            isolation="worktree",
            planModeRequired="true",
        )
    )
    assert definition.disallowed_tools == ("write_file",)
    assert definition.model == "sonnet"
    assert definition.max_turns == 12
    assert definition.permission_mode == "dontAsk"
    assert definition.background is True
    assert definition.isolation == "worktree"
    assert definition.plan_mode_required is True


def test_definition_parser_rejects_bad_fields() -> None:
    with pytest.raises(DefinitionParseError):
        parse_definition(_definition_text("ok", maxTurns="many"))
    with pytest.raises(DefinitionParseError):
        parse_definition(_definition_text("ok", permissionMode="super"))
    with pytest.raises(DefinitionParseError):
        parse_definition("没有 frontmatter 的正文")


def test_definition_parser_isolates_invalid_isolation_to_empty(tmp_path: Path) -> None:
    definition = parse_definition(_definition_text("ok", isolation="outer-space"))
    assert definition.isolation == ""


def test_definition_file_parser_requires_name_match(tmp_path: Path) -> None:
    path = tmp_path / "explore-v2.md"
    path.write_text(_definition_text("explore-v2"), encoding="utf-8")
    definition = parse_definition_file(path, source=Source.PROJECT)
    assert definition.name == "explore-v2"
    assert definition.source is Source.PROJECT

    mismatched = tmp_path / "other.md"
    mismatched.write_text(_definition_text("explore-v2"), encoding="utf-8")
    with pytest.raises(DefinitionParseError):
        parse_definition_file(mismatched)


def test_definition_is_immutable() -> None:
    definition = parse_definition(_definition_text("immutable"))
    with pytest.raises(Exception):
        definition.name = "changed"  # type: ignore[misc]
