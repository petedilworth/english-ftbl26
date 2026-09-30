"""
How long a club has been out of step with its own level, and what
usually happens next.

WHY THIS EXISTS. The natural-level page ranked clubs by the gap between
where they sit and where their record puts them. The gap is a whole
number of divisions and takes five values, so 41 clubs were tied at one
division below and the ranking inside that tie was alphabetical - a
league table with no league in it. Meanwhile the thing that separates
those 41 clubs was not on the page at all: Grimsby Town had been below
their level for 23 consecutive seasons and sat beside clubs one season
out of step, indistinguishable.

So this measures duration. A spell is the run of consecutive seasons,
counting back from the latest, on the same side of the club's level.
Ranked by that, everyone separates, and the two tables become what they
should have been: the longest spells above, and the longest spells below.

THE MODEL'S OWN LIMIT, STATED. The natural level is the balance of a
club's whole record, so a club that changed level fifteen years ago is
still measured against an era that has ended. Swansea have been "above
their level" for nineteen seasons. At some point that stops being a
description of Swansea and becomes a description of the model. Past
NEW_NORMAL_SEASONS the page says so, on the row, rather than letting the
table imply a club is due a fall it has spent a decade not taking.

WHAT USUALLY HAPPENS NEXT, MEASURED. The page used to assert that
"climbing above your level is usually a moment; falling below it is
usually structural". rolling_outcomes() tests that: for every club-season
in the record where a club sat out of step with its level AS JUDGED AT
THE TIME - the level recomputed from only the seasons up to then, so no
hindsight leaks in - it records where the club was three seasons later.
The intro can then say what the record says, with the numbers, instead of
what it sounded like it should say.
"""

from __future__ import annotations

import sqlite3
import statistics

import level as level_mod

# After this many seasons on the same side of its level, the level is the
# thing that is probably wrong. Ten is a generation of players and two of
# managers; nothing about a club that has spent ten years somewhere is a
# moment.
NEW_NORMAL_SEASONS = 10

# How far ahead rolling_outcomes() looks. Three seasons is long enough for
# a promotion or relegation to have happened and short enough that most
# spells in the record have a "three seasons later" to look at.
LOOK_AHEAD = 3

# A spell of three seasons or fewer is what the page's old intro would
# have called "a moment".
MOMENT_SEASONS = 3


def spell_length(history: dict[int, int], nl_tier: int, gap: int, latest: int) -> tuple[int, int]:
    """
    (seasons, since) for the run the club is currently on: consecutive
    recorded seasons back from `latest` on the same side of nl_tier as
    `gap` says the club is now.

    A season inside the club's window with no row is a season below the
    recorded pyramid, and counts as one - exactly as level.window_buckets
    counts it when computing the level in the first place. So it extends a
    spell below and ends a spell above. Before the club's first recorded
    season there is no window, and the run stops.
    """
    if not history:
        return 0, latest + 1
    first = min(history)
    run = 0
    year = latest
    while year >= first:
        tier = history.get(year, level_mod.OUTSIDE)
        on_this_side = tier < nl_tier if gap < 0 else tier > nl_tier
        if not on_this_side:
            break
        run += 1
        year -= 1
    return run, latest - run + 1


def current_spells(conn: sqlite3.Connection) -> list[dict]:
    """
    Every club playing now that sits above or below its level, with how
    long it has been there. Sorted longest first, then by distance, then
    by name, so the order is the same on every build.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(club_trajectory)")}
    if "natural_level_gap" not in cols:
        return []
    latest = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    histories = level_mod.load_histories(conn)

    out = []
    rows = conn.execute(
        """
        SELECT club_id, canonical_name, natural_level_tier, natural_level_label,
               natural_level_trend, natural_level_gap, current_tier, coverage_note
          FROM club_trajectory
         WHERE natural_level_gap IS NOT NULL AND natural_level_gap <> 0
           AND last_season_in_db = ?
        """,
        (latest,),
    ).fetchall()
    for (club_id, name, nl_tier, label, trend, gap, current, note) in rows:
        run, since = spell_length(histories.get(club_id, {}), nl_tier, gap, latest)
        out.append({
            "club_id": club_id,
            "name": name,
            "natural_level_tier": nl_tier,
            "natural_level_label": label,
            "current_tier": current,
            "coverage_note": note,
            "gap": gap,
            "direction": "above" if gap < 0 else "below",
            "trend": trend,
            "seasons": run,
            "since": since,
            "new_normal": run >= NEW_NORMAL_SEASONS,
        })
    out.sort(key=lambda s: (-s["seasons"], -abs(s["gap"]), s["name"]))
    return out


def summarise(spells: list[dict]) -> dict:
    """The figures above the tables, for one direction or both."""
    if not spells:
        return {"n": 0}
    lengths = sorted(s["seasons"] for s in spells)
    return {
        "n": len(spells),
        "moment": sum(1 for s in spells if s["seasons"] <= MOMENT_SEASONS),
        "new_normal": sum(1 for s in spells if s["new_normal"]),
        "median": statistics.median_low(lengths),
        "trend": {
            key: sum(1 for s in spells if s["trend"] == key)
            for key in ("rising", "level", "falling")
        },
    }


# ── what usually happens next ──────────────────────────────────────────────

def _level_at(history: dict[int, int], year: int) -> int | None:
    """The club's natural level as it would have been judged in `year`."""
    seen = {y: t for y, t in history.items() if y <= year}
    nl = level_mod.natural_level(seen)
    if nl.tier is None or nl.tier == level_mod.OUTSIDE:
        return None
    return nl.tier


def _outcome(gap_then: int, gap_later: int) -> str:
    if gap_later == 0:
        return "back"
    if (gap_then > 0) != (gap_later > 0):
        return "crossed"
    if abs(gap_later) > abs(gap_then):
        return "further"
    return "still"


def rolling_outcomes(histories: dict[str, dict[int, int]], latest: int) -> dict:
    """
    For every club-season out of step with the level AS JUDGED THEN, where
    the club was LOOK_AHEAD seasons later, relative to that same level.

    Keyed by (direction, distance), distance being 1 or "2+". Each value
    counts the four outcomes: back at the level, still on the same side,
    further away, or crossed to the other side.

    Only seasons whose "three seasons later" is inside the club's record
    count. A club absent from the record three seasons on has dropped
    below what the record reaches, which for a club below its level is
    "further" and for one above it is "crossed" - and it is counted so,
    because OUTSIDE sorts below every tier. A club whose record simply
    ends before then is not counted at all.
    """
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for history in histories.values():
        if not history:
            continue
        first, last = min(history), max(history)
        for year in range(first, last + 1):
            tier = history.get(year)
            if tier is None:
                continue
            later_year = year + LOOK_AHEAD
            if later_year > last or later_year > latest:
                continue
            nl = _level_at(history, year)
            if nl is None:
                continue
            gap = tier - nl
            if gap == 0:
                continue
            later_tier = history.get(later_year, level_mod.OUTSIDE)
            later_gap = later_tier - nl
            key = ("above" if gap < 0 else "below", "1" if abs(gap) == 1 else "2+")
            bucket = counts.setdefault(key, {"back": 0, "still": 0, "further": 0, "crossed": 0})
            bucket[_outcome(gap, later_gap)] += 1
    for bucket in counts.values():
        bucket["n"] = sum(bucket[k] for k in ("back", "still", "further", "crossed"))
    return counts


# ── the finance claim ──────────────────────────────────────────────────────

# Below this many clubs in a group, a median is a coincidence.
MIN_FINANCE_GROUP = 8


def wage_share_by_group(conn: sqlite3.Connection) -> dict[str, dict] | None:
    """
    Median wages as a share of turnover for clubs above, at and below
    their level, from each club's latest full set of accounts.

    The page used to say that falling below your level "does financial
    damage that compounds". This is the nearest thing the data can test,
    and it comes with its group sizes attached because they are small:
    a median of ten is a hint, and the copy has to call it one.
    """
    try:
        rows = conn.execute(
            """
            SELECT f.club_id, f.turnover, f.staff_costs, t.natural_level_gap
              FROM club_finances f
              JOIN club_trajectory t ON t.club_id = f.club_id
             WHERE f.disclosure = 'full' AND f.turnover > 0 AND f.staff_costs > 0
               AND t.natural_level_gap IS NOT NULL
               AND f.season_end_year = (
                   SELECT MAX(g.season_end_year) FROM club_finances g
                    WHERE g.club_id = f.club_id AND g.disclosure = 'full')
            """
        ).fetchall()
    except sqlite3.Error:
        return None
    groups: dict[str, list[float]] = {"above": [], "at": [], "below": []}
    for _club, turnover, staff, gap in rows:
        groups["above" if gap < 0 else "below" if gap > 0 else "at"].append(staff / turnover)
    if any(len(v) < MIN_FINANCE_GROUP for v in groups.values()):
        return None
    return {k: {"n": len(v), "median": statistics.median(v)} for k, v in groups.items()}
