"""
What this site's data actually covers, computed rather than asserted.

WHY THIS MODULE EXISTS. Coverage was being written down by hand in prose,
next to constants that describe the same thing, and only one of the two was
ever maintained. level.TIER5_FIRST_SEASON moved from 2005 to 1980 when the
engsoccerdata backfill landed - its own comment records the move and why it
mattered - while templates/team.html went on telling 355 club pages "tier 5
only from 2005/06". Wrong by twenty-six seasons, and by then also silent
about tiers 6 and 7.

That is a recurring failure rather than one slip. A page saying it plots
"all five tiers" after a seventh arrived, a footer reading "Tiers 1-5", a
provenance line reading "229 of 116 clubs", a matrix quietly dropping two
levels: every one was a claim about coverage that no longer matched the
data, and none of them could fail a test, because nothing computed the
truth to compare against.

So: one function that reads the database, and every rendered claim derived
from it. A caveat that drifts is then a test failure rather than something
noticed in a screenshot months later.

WHAT "COVERED" MEANS HERE. Two different things, and they part company:
a season can have a full league table and no match dates at all. Tier 5
has tables from 1979/80 but dated matches only from 1999/2000; tiers 6 and
7 have tables to the present but dated matches stop in 2018/19, because
the Wikipedia results grids they come from carry scores and no dates. Any
feature built on dates - form, streaks, the digest - therefore covers a
different range than the tables do, and only this distinction shows it.
"""

from __future__ import annotations

import sqlite3

# Club-level fields worth reporting, in the order a reader cares about
# them: where they are now first, then the things the charts consume.
# The label is the noun the page uses, so the same wording appears in the
# coverage table and in the sentence explaining it.
CLUB_FIELDS = [
    ("current_tier", "where they play now", "club_master"),
    ("latitude", "map coordinates", "club_master"),
    ("stadium_name", "ground", "club_master"),
    ("color_primary", "club colours", "club_master"),
]


def _minmax(conn: sqlite3.Connection, sql: str, params: tuple) -> tuple | None:
    lo, hi = conn.execute(sql, params).fetchone()
    return None if lo is None else (lo, hi)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """
    Optional columns are feature-detected everywhere else in this codebase
    (site_build.standings_cols, charts._ladder_position) because a database
    built before a migration still has to render. Coverage is the last
    place that should assume a column exists.
    """
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def tier_coverage(conn: sqlite3.Connection) -> list[dict]:
    """
    Per tier: the seasons of standings, and the seasons of DATED matches.

    The two are reported separately because they genuinely differ, and a
    reader who wants to know why a club has no form guide is asking about
    the second one.
    """
    standings_cols = _columns(conn, "standings")
    matches_cols = _columns(conn, "matches")
    out = []
    for (tier,) in conn.execute(
        "SELECT DISTINCT tier FROM standings ORDER BY tier"
    ).fetchall():
        table = _minmax(
            conn,
            "SELECT MIN(season_end_year), MAX(season_end_year)"
            " FROM standings WHERE tier = ?", (tier,))
        dated = _minmax(
            conn,
            "SELECT MIN(season_end_year), MAX(season_end_year) FROM matches"
            " WHERE tier = ? AND match_date IS NOT NULL", (tier,)
        ) if "match_date" in matches_cols else None
        incomplete = conn.execute(
            "SELECT COUNT(DISTINCT season_end_year) FROM standings"
            " WHERE tier = ? AND data_complete = 0", (tier,)
        ).fetchone()[0] if "data_complete" in standings_cols else 0
        out.append({
            "tier": tier,
            "seasons": table,
            "dated_matches": dated,
            "incomplete_seasons": incomplete,
        })
    return out


def field_coverage(conn: sqlite3.Connection) -> list[dict]:
    """Per club-level field: how many of the clubs on file carry it."""
    total = conn.execute("SELECT COUNT(*) FROM club_master").fetchone()[0]
    present = _columns(conn, "club_master")
    out = []
    for column, label, _table in CLUB_FIELDS:
        if column not in present:
            continue
        n = conn.execute(
            f"SELECT COUNT(*) FROM club_master"
            f" WHERE {column} IS NOT NULL AND {column} <> ''").fetchone()[0]
        out.append({"key": column, "label": label, "have": n, "total": total})

    for table, label in (("club_catchment", "catchment modelled"),
                         ("club_finances", "accounts collected")):
        try:
            n = conn.execute(
                f"SELECT COUNT(DISTINCT club_id) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            continue
        out.append({"key": table, "label": label, "have": n, "total": total})
    return out


def first_season(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT MIN(season_end_year) FROM standings").fetchone()[0]


def natural_level_caveat(conn: sqlite3.Connection) -> str:
    """
    The sentence under a club's natural-level bar, saying what the bar can
    and cannot see.

    This is the one that was hardcoded. It has to name the season each
    tier's record starts, because a gap before that is "we cannot see it"
    rather than "they were not there" - which is exactly what the bar
    would otherwise imply about a club's non-league years.
    """
    import level as level_mod

    rows = {c["tier"]: c for c in tier_coverage(conn)}
    start = first_season(conn)

    # Group the late-starting tiers by the season they begin, because the
    # sixth and seventh start together and naming each separately reads as
    # two facts when it is one.
    by_start: dict[int, list[int]] = {}
    for tier, c in sorted(rows.items()):
        if c["seasons"] and c["seasons"][0] > start:
            by_start.setdefault(c["seasons"][0], []).append(tier)

    clauses = []
    for began, tiers in sorted(by_start.items()):
        if len(tiers) == 1:
            who = level_mod.the(tiers[0])
        else:
            who = "the " + _ordinals(tiers) + " tiers"
        clauses.append(f"{who} only from {_season(began)}")

    if not clauses:
        return f"Measured from {_season(start)}."
    return (f"Measured from {_season(start)} — {_join(clauses)}. A gap before "
            f"those is a level this site cannot see, not a season the club "
            f"did not play.")


ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth",
            5: "fifth", 6: "sixth", 7: "seventh"}


def _ordinals(tiers: list[int]) -> str:
    return _join([ORDINALS.get(t, str(t)) for t in tiers])


def _join(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _season(end_year: int) -> str:
    return f"{end_year - 1}/{end_year % 100:02d}"


def ranked_note(conn: sqlite3.Connection, complete_only: bool = True) -> str:
    """
    The line under a page that ranks clubs against each other.

    Pages like records, yo-yo and safe thresholds read as if they cover
    "English football". They cover what this database holds, which is a
    narrower and uneven thing - the fifth tier joins in 1979/80 and the
    sixth and seventh in 2012/13, so a club's earlier seasons at those
    levels are not absent from the game, only from here. Saying so is the
    difference between a ranking and a ranking you can trust.

    complete_only is for the tables built by _standings_section, which
    already refuse a season whose fixtures are short: a superlative drawn
    from a part-played table is an artifact rather than a record.
    """
    rows = tier_coverage(conn)
    if not rows:
        return ""
    lo = min(c["seasons"][0] for c in rows if c["seasons"])
    hi = max(c["seasons"][1] for c in rows if c["seasons"])
    deepest = max(c["tier"] for c in rows)

    note = (f"Drawn from tiers 1–{deepest}, {_season(lo)} to {_season(hi)}, "
            f"as far as the record reaches at each level")
    late = sorted({c["seasons"][0] for c in rows if c["seasons"]} - {lo})
    if late:
        note += f" — the lower tiers join later, from {_join([_season(y) for y in late])}"
    note += "."
    if complete_only:
        note += (" A season whose fixtures are incomplete is withheld, because "
                 "a total drawn from a part-played table is not the total that "
                 "decided anything.")
    return note
