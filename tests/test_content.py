import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from content import (
    derive_themes,
    load_club,
    parse_front_matter,
    split_sections,
)


# ── Front matter ───────────────────────────────────────────────────────

def test_front_matter_parsed_and_stripped():
    facts, body = parse_front_matter(
        "---\nfounded: 1905\nowner: Someone\n---\nThe prose starts here.\n"
    )
    assert facts == {"founded": 1905, "owner": "Someone"}
    assert body.strip() == "The prose starts here."


def test_no_front_matter_returns_whole_body():
    facts, body = parse_front_matter("Just prose, no fences.\n")
    assert facts == {}
    assert body.strip() == "Just prose, no fences."


def test_malformed_front_matter_does_not_raise():
    # Unbalanced brackets - yaml will refuse. The build must survive it.
    facts, body = parse_front_matter("---\nfounded: [1905\n---\nProse.\n")
    assert facts == {}
    assert "Prose." in body


def test_non_mapping_front_matter_ignored():
    facts, _ = parse_front_matter("---\n- just\n- a list\n---\nProse.\n")
    assert facts == {}


def test_nested_lists_survive():
    facts, _ = parse_front_matter(
        "---\n"
        "administration:\n"
        "  - year: 2010\n"
        "    points_deducted: 9\n"
        "---\n"
    )
    assert facts["administration"] == [{"year": 2010, "points_deducted": 9}]


# ── Sections ───────────────────────────────────────────────────────────

def test_canonical_sections_split():
    sections, extra = split_sections(
        "## Origins\nFounded by railwaymen.\n\n"
        "## Ownership & Finance\nBought in 2003.\n"
    )
    assert sections["origins"] == "Founded by railwaymen."
    assert sections["ownership & finance"] == "Bought in 2003."
    assert extra == ""


def test_section_heading_aliases():
    sections, _ = split_sections(
        "## Ownership and Finance\nA.\n\n## Infrastructure\nB.\n"
    )
    assert sections["ownership & finance"] == "A."
    assert sections["infrastructure & environment"] == "B."


def test_unrecognised_heading_kept_as_extra():
    sections, extra = split_sections(
        "## Origins\nKnown.\n\n## Kit history\nUnknown section.\n"
    )
    assert sections["origins"] == "Known."
    assert "Kit history" in extra
    assert "Unknown section." in extra


def test_prose_without_headings_becomes_extra():
    sections, extra = split_sections("Just a paragraph.\n")
    assert sections == {}
    assert extra == "Just a paragraph."


def test_preamble_before_first_heading_kept():
    sections, extra = split_sections("Intro line.\n\n## Origins\nBody.\n")
    assert sections["origins"] == "Body."
    assert "Intro line." in extra


def test_empty_section_skipped():
    sections, _ = split_sections("## Origins\n\n## Trajectory\nReal content.\n")
    assert "origins" not in sections
    assert sections["trajectory"] == "Real content."


# ── Theme derivation ───────────────────────────────────────────────────

def test_themes_derived_from_facts():
    cases = [
        ({"phoenix_of": "wimbledon-fc"}, "phoenix"),
        ({"ownership_model": "fan_trust"}, "fan-owned"),
        ({"administration": [{"year": 2010}]}, "administration"),
        ({"points_deductions": [{"points": 10}]}, "points-deductions"),
        ({"exile": [{"venue": "Elsewhere"}]}, "exiled"),
        ({"ground_grading_denial": [{"season_end_year": 1996}]}, "ground-grading"),
        ({"stadium_ownership": "council"}, "council-ground"),
        ({"multi_club_group": "Some Group"}, "multi-club"),
        ({"previous_grounds": [{"name": "Old Park"}]}, "stadium-moves"),
    ]
    for facts, expected in cases:
        assert expected in derive_themes(facts), f"{facts} should yield {expected}"


def test_no_facts_yields_no_themes():
    assert derive_themes({}) == []


def test_club_owned_stadium_is_not_council_theme():
    assert "council-ground" not in derive_themes({"stadium_ownership": "club"})


def test_manual_themes_merged_and_deduped():
    themes = derive_themes(
        {"ownership_model": "fan_trust", "themes": ["taylor-report", "fan-owned"]}
    )
    assert themes.count("fan-owned") == 1
    assert "taylor-report" in themes


def test_manual_theme_accepts_bare_string():
    assert "solo" in derive_themes({"themes": "solo"})


# ── Whole-file loading ─────────────────────────────────────────────────

def test_load_club_missing_file_returns_none(tmp_path):
    assert load_club(tmp_path / "nobody.md") is None


def test_load_club_end_to_end(tmp_path):
    path = tmp_path / "club.md"
    path.write_text(
        "---\n"
        "founded: 1889\n"
        "ownership_model: fan_trust\n"
        "exile:\n"
        "  - venue: Somewhere Else\n"
        "    seasons: 1997-1999\n"
        "---\n"
        "## Origins\nA church team.\n\n"
        "## Trajectory\nUp and down.\n",
        encoding="utf-8",
    )
    club = load_club(path)
    assert club["facts"]["founded"] == 1889
    assert club["sections"]["origins"] == "A church team."
    assert set(club["themes"]) == {"fan-owned", "exiled"}
    assert club["has_prose"] is True


def test_load_club_facts_only_has_no_prose(tmp_path):
    path = tmp_path / "facts-only.md"
    path.write_text("---\nfounded: 1889\n---\n", encoding="utf-8")
    club = load_club(path)
    assert club["facts"]["founded"] == 1889
    assert club["has_prose"] is False
