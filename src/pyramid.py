"""
The whole pyramid, season by season, as one small file for the browser.

The Replay page moves every club through every season it has a row for,
and the allocation notice draws a club's life from the same rows. Both
need what the Matrix page has - who was where, in what order - but as
data rather than as a table of ten thousand spans, so it is assembled
here once and written to data/pyramid.json.

WHAT A ROW IS. One club in one season: its tier, its rank across the whole
of that tier, its division, its position in that division, and how the
season ended for it. Rank and position differ only where a tier is more
than one division: the sixth tier's two champions are both first in their
division and first and second in the tier. The Replay lays a tier out by
rank, which is the same choice the Matrix made and for the same reason -
a level reads as one standing.

WHY IT IS FLAT. The file is the same six numbers nine thousand times, so
it is written as six numbers nine thousand times: a flat list per season
and two lookup lists, clubs and division names. As objects it was three
times the size for the same information.
"""

import sqlite3

import aggregate
import level as level_mod

# How a season ended for a club, as the browser gets it. The order is the
# file format: static/replay.js and static/allocation.js index into it.
KINDS = ["Stayed", "Champions", "Promoted", "Play-off Promoted", "Relegated",
         "Play-off Relegated", "In progress"]
KIND_CODE = {name: i for i, name in enumerate(KINDS)}

# What one row of a season is made of, in order.
ROW = ("club", "tier", "rank", "division", "position", "kind")


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def band_names(since: dict[int, int], last: int) -> dict[str, list]:
    """
    What each tier was called, as [season, name] at every change: the
    First Division is the Premier League from 1992/93, and the label on
    the Replay changes in the year it happened. A tier several divisions
    wide has no competition name, so it takes the level's. Each tier
    starts where its rows do.
    """
    out = {}
    for tier, first in sorted(since.items()):
        changes: list[list] = []
        for season in range(first, last + 1):
            name = (aggregate.get_division_name(tier, season) if tier <= 5
                    else level_mod.bucket_name(tier))
            if not changes or changes[-1][1] != name:
                changes.append([season, name])
        out[str(tier)] = changes
    return out


def assemble(conn: sqlite3.Connection, pages: set[str] | None = None) -> dict | None:
    """
    Every club-season in the record, ready to be written as JSON.

    `pages` is the set of clubs this build makes a page for; a club outside
    it still moves on the Replay but is not offered as a link. None means
    every club with an id.
    """
    cols = _columns(conn, "standings")
    if not cols:
        return None
    rank = "COALESCE(tier_position, position)" if "tier_position" in cols else "position"
    division = "division_id" if "division_id" in cols else "NULL"
    rows = conn.execute(
        f"SELECT season_end_year, tier, {rank}, club_id, club_name, division_name, position, status, {division}"
        f" FROM standings ORDER BY season_end_year, tier, {rank}, club_name").fetchall()
    if not rows:
        return None

    master_cols = _columns(conn, "club_master")
    colours = {}
    if "color_primary" in master_cols:
        colours = {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT club_id, color_primary, color_secondary FROM club_master")}
    names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))
    now = {}
    if "current_tier" in master_cols:
        now = dict(conn.execute("SELECT club_id, current_tier FROM club_master"))

    first, last = rows[0][0], rows[-1][0]
    clubs: list[list] = []
    club_index: dict[str, int] = {}
    divisions: list[str] = []
    division_index: dict[str, int] = {}
    seasons: list[list[int]] = [[] for _ in range(last - first + 1)]
    live = False

    for season, tier, tier_rank, club_id, club_name, division_name, position, status, _div_id in rows:
        # A row whose name never resolved to a club still played that
        # season; it is keyed on the name it was given and gets no page.
        key = club_id or f"name:{club_name}"
        if key not in club_index:
            a, b = colours.get(club_id, (None, None))
            club_index[key] = len(clubs)
            clubs.append([
                club_id if club_id and (pages is None or club_id in pages) else None,
                names.get(club_id) or club_name, a, b, now.get(club_id),
            ])
        division_name = division_name or f"Tier {tier}"
        if division_name not in division_index:
            division_index[division_name] = len(divisions)
            divisions.append(division_name)
        kind = KIND_CODE.get(status, 0)
        live = live or (season == last and status == "In progress")
        seasons[season - first].extend([
            club_index[key], tier, tier_rank or 0, division_index[division_name], position or 0, kind,
        ])

    tiers = sorted({r[1] for r in rows})
    since = {t: min(r[0] for r in rows if r[1] == t) for t in tiers}
    return {
        "first": first, "last": last, "live": live,
        "row": len(ROW), "kinds": KINDS, "tiers": tiers,
        "bands": band_names(since, last),
        # When each tier's rows begin: the bands below the fourth are empty
        # before these seasons because the record does not reach them, not
        # because nobody played, and the page says so.
        "since": {str(t): s for t, s in since.items()},
        "divisions": divisions,
        "clubs": clubs,
        "seasons": seasons,
    }


def history(data: dict, club: int) -> list[tuple[int, int, int, int, int, int]]:
    """One club's rows as (season, tier, rank, division, position, kind), oldest first."""
    out = []
    width = data["row"]
    for offset, flat in enumerate(data["seasons"]):
        for i in range(0, len(flat), width):
            if flat[i] == club:
                out.append((data["first"] + offset, *flat[i + 1:i + width]))
                break
    return out
