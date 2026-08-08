from Arkcode.prompt import render_active_skills, render_skill_catalog


def test_render_skill_catalog_lists_metadata_without_sop() -> None:
    rendered = render_skill_catalog(
        [("commit", "Create commits"), ("review", "Review code")]
    )

    assert rendered.startswith("## Available Skills")
    assert "- commit: Create commits" in rendered
    assert "- review: Review code" in rendered
    assert "call LoadSkill" in rendered
    assert "secret SOP" not in rendered


def test_render_skill_catalog_is_empty_without_items() -> None:
    assert render_skill_catalog([]) == ""


def test_render_active_skills_preserves_order_and_full_bodies() -> None:
    rendered = render_active_skills({"review": "Check bugs", "commit": "Write message"})

    assert rendered.startswith("## Active Skills")
    assert rendered.index("### Skill: review") < rendered.index("### Skill: commit")
    assert "Check bugs" in rendered
    assert "Write message" in rendered


def test_render_active_skills_is_empty_without_entries() -> None:
    assert render_active_skills({}) == ""
