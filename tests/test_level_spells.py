"""
How long a club has been out of step with its level, and what the record
says usually happens next.

The page this feeds used to rank on a number that took five values and
assert an outcome it never measured. These tests pin the two things that
replaced that: a spell length that counts what the level model counts,
and an outcome table judged without hindsight.
"""
import re
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import level                                             # noqa: E402
import levelspells                                       # noqa: E402

SITE = PROJECT_ROOT / "site"
DB = PROJECT_ROOT / "data" / "db" / "england.db"


# ── spell length ───────────────────────────────────────────────────────────

def test_a_spell_counts_back_from_the_latest_season():
    history = {2020: 3, 2021: 3, 2022: 2, 2023: 2, 2024: 2}
    seasons, since = levelspells.spell_length(history, nl_tier=3, gap=-1, latest=2024)
    assert (seasons, since) == (3, 2022)


def test_a_season_at_the_level_ends_the_spell():
    history = {2020: 2, 2021: 3, 2022: 2, 2023: 2, 2024: 2}
    assert levelspells.spell_length(history, 3, -1, 2024)[0] == 3


def test_a_season_below_the_recorded_pyramid_extends_a_spell_below():
    """
    level.window_buckets counts a missing season inside the window as
    below everything, so a spell below must too - FC Halifax Town were
    below their level through six seasons the record has no row for,
    and those are the seasons the level was computed on.
    """
    history = {2010: 4, 2011: 5, 2015: 5, 2016: 5}     # 2012-14 outside
    seasons, since = levelspells.spell_length(history, 4, +1, 2016)
    assert (seasons, since) == (6, 2011)


def test_a_season_below_the_recorded_pyramid_ends_a_spell_above():
    history = {2010: 4, 2013: 2, 2014: 2}
    assert levelspells.spell_length(history, 3, -1, 2014)[0] == 2


def test_a_spell_cannot_reach_before_the_first_recorded_season():
    history = {2022: 1, 2023: 1, 2024: 1}
    seasons, since = levelspells.spell_length(history, 2, -1, 2024)
    assert (seasons, since) == (3, 2022)


# ── what happens next ──────────────────────────────────────────────────────

@pytest.mark.parametrize("then,later,expected", [
    (-1, 0, "back"), (+1, 0, "back"),
    (-1, -1, "still"), (+2, +1, "still"),
    (-1, -2, "further"), (+1, +2, "further"),
    (-1, +1, "crossed"), (+1, -2, "crossed"),
])
def test_an_outcome_is_named_for_where_the_club_went(then, later, expected):
    assert levelspells._outcome(then, later) == expected


def test_outcomes_are_judged_by_the_level_as_it_stood_then():
    """
    No hindsight. A club that has climbed for ten seasons is, in its
    early seasons, above the level its record had reached by then - and
    that is what it is judged against, not the level it ended with.
    """
    # Eight seasons at 4, then eight at 2: judged in 2012, the level is 4
    # and the club is two above it; judged at the end it would be a
    # different club.
    history = {y: 4 for y in range(2001, 2009)} | {y: 2 for y in range(2009, 2017)}
    out = levelspells.rolling_outcomes({"x": history}, latest=2016)
    assert ("above", "2+") in out
    assert out[("above", "2+")]["still"] >= 1
    assert ("below", "1") not in out


def test_a_club_gone_from_the_record_is_counted_as_below_it():
    """
    Absent three seasons on means dropped below what the record reaches,
    which for a club below its level is "further" - not skipped, and not
    "back".
    """
    history = {y: 4 for y in range(2000, 2010)} | {2010: 5, 2011: 5, 2012: 5, 2016: 5}
    out = levelspells.rolling_outcomes({"x": history}, latest=2016)
    below = out[("below", "1")]
    assert below["further"] >= 1


def test_every_outcome_bucket_sums_to_its_n():
    if not DB.exists():
        pytest.skip("database not built")
    conn = sqlite3.connect(DB)
    latest = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    out = levelspells.rolling_outcomes(level.load_histories(conn), latest)
    assert out, "no outcomes from the real record"
    for bucket in out.values():
        assert sum(bucket[k] for k in ("back", "still", "further", "crossed")) == bucket["n"]


# ── the summary ────────────────────────────────────────────────────────────

def test_the_summary_counts_moments_and_new_normals():
    spells = [{"seasons": s, "new_normal": s >= 10, "trend": "level"}
              for s in (1, 2, 3, 4, 10, 15)]
    summary = levelspells.summarise(spells)
    assert summary["n"] == 6
    assert summary["moment"] == 3
    assert summary["new_normal"] == 2
    assert summary["median"] == 3


# ── the page ───────────────────────────────────────────────────────────────

def _page():
    path = SITE / "insights" / "natural-level" / "index.html"
    if not path.exists():
        pytest.skip("site not built")
    return path.read_text()


def test_the_page_names_no_starting_season_it_did_not_derive():
    """
    It said "since 1993/94" for thirty-five seasons after the backfill
    moved the record to 1958/59. The season is read from the data now.
    """
    html = _page()
    assert "1993" not in html
    conn = sqlite3.connect(DB)
    import coverage
    first = coverage.first_season(conn)
    assert f"{first - 1}/{first % 100:02d}" in html


def test_every_row_links_to_the_club_s_own_level_bar():
    html = _page()
    links = re.findall(r'href="([^"]*?/team/[^"]+)"', html)
    assert links, "no club links on the page"
    assert all(link.endswith("#natural-level") for link in links)
    # and the anchor exists on a club page
    sample = links[0].split("/team/")[1].split("/")[0]
    club = (SITE / "team" / sample / "index.html").read_text()
    assert 'id="natural-level"' in club


def test_each_table_is_ranked_by_how_long_not_by_how_far():
    html = _page()
    for heading in ("Playing above their level", "Playing below their level"):
        section = html.split(heading, 1)[1].split("</table>", 1)[0]
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", section, re.S)[1:]
        seasons = [int(re.findall(r'<td class="num">(\d+)</td>', r)[-1]) for r in rows]
        assert seasons == sorted(seasons, reverse=True), heading
        assert len(set(seasons)) > 5, "the ranking must actually separate clubs"


def test_a_decade_long_spell_is_marked_as_the_model_s_limit():
    html = _page()
    section = html.split("Playing above their level", 1)[1].split("</table>", 1)[0]
    rows = re.findall(r"<tr([^>]*)>(.*?)</tr>", section, re.S)[1:]
    for attrs, body in rows:
        seasons = int(re.findall(r'<td class="num">(\d+)</td>', body)[-1])
        marked = "new-normal" in attrs
        assert marked == (seasons >= levelspells.NEW_NORMAL_SEASONS), body[:80]
        assert ("probably their level now" in body) == marked


def test_the_outcome_table_rows_add_to_a_hundred():
    html = _page()
    section = html.split("What usually happens next", 1)[1].split("</table>", 1)[0]
    rows = re.findall(r"<tr>(.*?)</tr>", section, re.S)[1:]
    assert rows
    for row in rows:
        pcts = [int(x) for x in re.findall(r">(\d+)%<", row)]
        assert len(pcts) == 4
        assert 98 <= sum(pcts) <= 102, row


def test_the_finance_claim_carries_its_group_sizes():
    """A median of ten clubs is a hint, and the copy has to say so."""
    html = _page()
    if "And the money" not in html:
        pytest.skip("finance groups too small to render")
    text = html.split("And the money", 1)[1].split("</p>", 1)[0]
    assert re.search(r"\(\d+ clubs\)", text)
    assert "hint" in text
