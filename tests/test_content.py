import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from content import (
    derive_themes,
    first_year,
    load_club,
    load_theme,
    parse_front_matter,
    split_sections,
    theme_events,
    theme_narrative,
    to_season_end_year,
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


# ── Year parsing ───────────────────────────────────────────────────────
# The schema mixes calendar years with season-end years, and the range
# fields are free text using an en-dash. Both have already caused wrong
# dates, so they're pinned here.

def test_first_year_handles_every_shape_in_the_corpus():
    cases = [
        (2013, 2013),                 # plain int
        ("1997–1999", 1997),     # en-dash range, as the files actually use
        ("1985-1991", 1985),          # hyphen range
        ("2019–2021", 2019),
        ("opened 1919", 1919),        # year embedded in prose
        (None, None),
        ("no year here", None),
        (42, None),                   # out of plausible range
    ]
    for value, expected in cases:
        assert first_year(value) == expected, value


def test_calendar_years_shift_onto_the_season_axis():
    # A season starting in calendar year N ends in N+1, which is the axis
    # the standings table and both charts are keyed on.
    assert to_season_end_year(2013, "calendar") == 2014
    assert to_season_end_year(2014, "season") == 2014
    assert to_season_end_year(None, "calendar") is None


def test_coventrys_administration_and_deduction_land_on_one_season():
    # The real trap: administration.year is 2013 (calendar) and
    # points_deductions.season_end_year is 2014 - the same 2013/14 saga.
    facts = {
        "administration": [{"year": 2013, "points_deducted": 10}],
        "points_deductions": [{"season_end_year": 2014, "points": 10}],
    }
    admin = theme_events("administration", facts)
    deduction = theme_events("points-deductions", facts)
    assert admin[0]["season_end_year"] == deduction[0]["season_end_year"] == 2014


# ── Theme events ───────────────────────────────────────────────────────

def test_theme_events_per_theme():
    cases = [
        ("administration", {"administration": [{"year": 2010, "points_deducted": 9}]}, 2011),
        ("points-deductions", {"points_deductions": [{"season_end_year": 2014, "points": 3}]}, 2014),
        ("exiled", {"exile": [{"venue": "Elsewhere", "seasons": "1997–1999"}]}, 1998),
        ("ground-grading", {"ground_grading_denial": [{"season_end_year": 1996}]}, 1996),
        ("phoenix", {"founded": 2002, "phoenix_of": "Old FC"}, 2003),
        ("stadium-moves", {"stadium": "New Park", "stadium_opened": 2005}, 2006),
        ("fan-owned", {"owner_since": 2003, "owner": "The Trust"}, 2004),
    ]
    for slug, facts, expected in cases:
        events = theme_events(slug, facts)
        assert events, f"{slug} should yield an event"
        assert events[0]["season_end_year"] == expected, slug
        assert events[0]["text"], f"{slug} event needs text"


def test_themes_without_a_natural_date_yield_no_dots():
    assert theme_events("council-ground", {"stadium_ownership": "council"}) == []
    assert theme_events("multi-club", {"multi_club_group": "A Group"}) == []


def test_events_are_sorted_oldest_first():
    facts = {"exile": [
        {"venue": "Later", "seasons": "2019–2021"},
        {"venue": "Earlier", "seasons": "2013–2014"},
    ]}
    years = [e["season_end_year"] for e in theme_events("exiled", facts)]
    assert years == sorted(years)


def test_undated_entries_are_skipped_not_crashed():
    assert theme_events("administration", {"administration": [{"note": "no year"}]}) == []
    assert theme_events("exiled", {"exile": [{"venue": "Nowhere"}]}) == []
    assert theme_events("points-deductions", {"points_deductions": ["not a dict"]}) == []
    assert theme_events("administration", {}) == []


# ── Theme narrative ────────────────────────────────────────────────────

def test_narrative_derived_from_facts():
    text = theme_narrative("administration", {
        "administration": [{"year": 2013, "points_deducted": 10,
                            "note": "Followed a rent dispute"}],
    })
    assert "2013" in text and "10 points" in text and "rent dispute" in text


def test_narrative_singular_point_reads_correctly():
    text = theme_narrative("points-deductions", {
        "points_deductions": [{"season_end_year": 2014, "points": 1}],
    })
    assert "1 point." in text or "1 point " in text
    assert "1 points" not in text


def test_theme_notes_override_the_derived_text():
    facts = {
        "administration": [{"year": 2010, "points_deducted": 9}],
        "theme_notes": {"administration": "A richer hand-written passage."},
    }
    assert theme_narrative("administration", facts) == "A richer hand-written passage."
    # Other themes are unaffected by an override aimed at one of them
    assert "9 points" in theme_narrative("administration", {
        "administration": [{"year": 2010, "points_deducted": 9}]})


def test_undated_themes_still_get_a_sentence():
    assert "local authority" in theme_narrative(
        "council-ground", {"stadium": "St James Park", "stadium_ownership": "council"})
    assert "A Group" in theme_narrative("multi-club", {"multi_club_group": "A Group"})


def test_narrative_empty_when_nothing_to_say():
    assert theme_narrative("administration", {}) == ""


# ── Theme intros ───────────────────────────────────────────────────────

def test_load_theme_missing_file_is_empty(tmp_path):
    assert load_theme(tmp_path / "nope.md") == ""


def test_load_theme_reads_prose(tmp_path):
    path = tmp_path / "phoenix.md"
    path.write_text("Why this is a theme.\n", encoding="utf-8")
    assert load_theme(path) == "Why this is a theme."
