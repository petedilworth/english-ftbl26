"""
Coverage claims have to match the data, and nothing may hardcode one.

The bug that prompted this: level.TIER5_FIRST_SEASON moved from 2005 to
1980 when the engsoccerdata backfill landed, and templates/team.html went
on telling 355 club pages "tier 5 only from 2005/06" - wrong by
twenty-six seasons, and later silent about tiers 6 and 7 as well. A
sentence describing coverage sat next to a constant describing coverage,
and only one of them was maintained.
"""
import re
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import coverage as coverage_mod  # noqa: E402

DB = PROJECT_ROOT / "data" / "db" / "england.db"
SITE = PROJECT_ROOT / "site"
TEMPLATES = PROJECT_ROOT / "templates"


def _conn():
    if not DB.exists():
        pytest.skip("no built database")
    return sqlite3.connect(DB)


def test_every_tier_reports_a_season_range():
    rows = coverage_mod.tier_coverage(_conn())
    assert rows, "no tiers reported"
    for row in rows:
        assert row["seasons"], f"tier {row['tier']} has no season range"
        lo, hi = row["seasons"]
        assert lo <= hi


def test_dated_matches_never_claim_more_than_the_tables():
    """
    Dates are a subset of what the tables cover, never a superset. A tier
    reporting dated matches outside its own standings range means matches
    are stored for a season with no table, which is a load-order bug.
    """
    for row in coverage_mod.tier_coverage(_conn()):
        if not row["dated_matches"]:
            continue
        (t_lo, t_hi), (d_lo, d_hi) = row["seasons"], row["dated_matches"]
        assert t_lo <= d_lo and d_hi <= t_hi, (
            f"tier {row['tier']}: dated matches {d_lo}-{d_hi} outside "
            f"tables {t_lo}-{t_hi}")


def test_the_caveat_names_the_seasons_the_data_actually_starts():
    """
    The sentence on every club page. It has to name each late-starting
    level's real first season - the failure it replaces named one that was
    twenty-six years out.
    """
    conn = _conn()
    caveat = coverage_mod.natural_level_caveat(conn)
    start = coverage_mod.first_season(conn)
    assert f"{start - 1}/{start % 100:02d}" in caveat

    for row in coverage_mod.tier_coverage(conn):
        began = row["seasons"][0]
        if began == start:
            continue
        label = f"{began - 1}/{began % 100:02d}"
        assert label in caveat, (
            f"tier {row['tier']} starts in {label} and the caveat does not say so")


def test_no_template_hardcodes_a_season_range():
    """
    The check that would have caught the original. A four-digit year in a
    caveat or note is a coverage claim written by hand, and it will drift
    from the data the next time the data moves. Jinja expressions are
    fine - those come from coverage.py.
    """
    offenders = []
    for path in TEMPLATES.glob("*.html"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if "{#" in line or line.strip().startswith("#"):
                continue
            if not re.search(r'class="(nl-caveat|coverage-note|finance-note)"', line):
                continue
            # A season written as 1958/59 or 2005/06, outside {{ }}.
            without_expressions = re.sub(r"\{\{.*?\}\}", "", line)
            if re.search(r"\b(18|19|20)\d{2}\s*/\s*\d{2}\b", without_expressions):
                offenders.append(f"{path.name}:{n}")
    assert not offenders, (
        "coverage years hardcoded in a caveat - derive them from "
        f"src/coverage.py instead: {offenders}")


def test_the_coverage_page_matches_the_database():
    page = SITE / "insights" / "coverage" / "index.html"
    if not page.exists():
        pytest.skip("site not built")
    html = page.read_text()
    conn = _conn()

    for row in coverage_mod.tier_coverage(conn):
        lo, hi = row["seasons"]
        span = f"{lo - 1}/{lo % 100:02d}–{hi - 1}/{hi % 100:02d}"
        assert span in html, f"tier {row['tier']} range {span} missing from the page"

    for field in coverage_mod.field_coverage(conn):
        assert f">{field['have']}<" in html, (
            f"{field['label']} count {field['have']} missing from the page")


def test_the_club_page_caveat_is_the_derived_one():
    page = SITE / "team" / "leiston-fc" / "index.html"
    if not page.exists():
        pytest.skip("site not built")
    html = page.read_text()
    assert "2005/06" not in html, "the stale hardcoded caveat is back"
    assert "1979/80" in html, "the caveat does not name the real tier-5 start"


RANKED_PAGES = ["yo-yo", "records", "safe-thresholds", "points-eras"]


def test_the_ranked_pages_say_what_they_cover():
    """
    These pages rank clubs against each other and read as if they cover
    English football. They cover what this database holds, which joins the
    fifth tier in 1979/80 and the sixth and seventh in 2012/13 - so a
    club's earlier seasons at those levels are missing from the ranking
    but not from the game. The line is derived, not written on the page,
    so it cannot drift the way the club-page caveat did.
    """
    conn = _conn()
    expected_open = coverage_mod.ranked_note(conn)[:60]
    missing = []
    for slug in RANKED_PAGES:
        page = SITE / "insights" / slug / "index.html"
        if not page.exists():
            continue
        if expected_open not in page.read_text():
            missing.append(slug)
    if not any((SITE / "insights" / s / "index.html").exists() for s in RANKED_PAGES):
        pytest.skip("site not built")
    assert not missing, f"ranked pages with no coverage line: {missing}"


def test_the_completeness_clause_is_only_on_pages_that_enforce_it():
    """
    records and safe-thresholds go through _standings_section, which
    refuses a season whose fixtures are short. yo-yo and points-eras do
    not, so claiming they withhold incomplete seasons would be a promise
    the page does not keep.
    """
    clause = "withheld"
    for slug, enforces in (("records", True), ("safe-thresholds", True),
                           ("yo-yo", False), ("points-eras", False)):
        page = SITE / "insights" / slug / "index.html"
        if not page.exists():
            continue
        note = page.read_text()
        assert (clause in note) == enforces, (
            f"{slug}: completeness clause present={clause in note}, "
            f"but the page enforces it={enforces}")


def test_the_catchment_essay_quotes_the_figures_the_model_produces():
    """
    content/insights/catchment.md names specific clubs and numbers. Those
    are hand-written and the model moves under them: Marine's contested
    share was 98.3% until the sixth and seventh tiers were added and gave
    them nearer neighbours than Liverpool and Everton, at which point the
    essay was wrong by a point and a half with nothing to catch it.
    """
    conn = _conn()
    doc = (PROJECT_ROOT / "content" / "insights" / "catchment.md").read_text()

    for club_id, column, quoted in (
        ("arsenal-fc", "catchment_pop_restored", "1,856,061"),
        ("leyton-orient-fc", "catchment_pop_current", "325,076"),
        ("leyton-orient-fc", "catchment_pop_restored", "1,665,263"),
    ):
        row = conn.execute(
            f"SELECT {column} FROM club_catchment WHERE club_id = ?",
            (club_id,)).fetchone()
        if not row or row[0] is None:
            continue
        assert quoted in doc, f"{club_id} no longer quoted in the essay"
        assert f"{row[0]:,}" == quoted, (
            f"{club_id} {column}: essay says {quoted}, model says {row[0]:,}")

    for club_id, quoted in (("portsmouth-fc", 3.6), ("marine-fc", 96.7)):
        row = conn.execute(
            "SELECT contest_ratio FROM club_catchment WHERE club_id = ?",
            (club_id,)).fetchone()
        if not row or row[0] is None:
            continue
        actual = round(row[0] * 100, 1)
        assert f"{quoted}% contested" in doc, f"{club_id} figure changed in the essay"
        assert abs(actual - quoted) < 0.05, (
            f"{club_id}: essay says {quoted}%, model says {actual}%")

    total = conn.execute("SELECT COUNT(*) FROM club_master").fetchone()[0]
    have = conn.execute("SELECT COUNT(*) FROM club_catchment").fetchone()[0]
    assert f"{have} of the {total} clubs" in doc, (
        f"the essay's coverage count is stale: the model has {have} of {total}")
