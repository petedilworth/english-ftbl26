"""
Every club's record against every club it has played.

WHY A MODULE AND NOT A QUERY. The record between two clubs already
existed - digest.head_to_head(conn, a, b) computes it for a fixture
preview - but nothing computed a club's record against all of its
opponents, and doing it the obvious way is a query per opponent per club:
355 clubs, 13,952 pairs, and a full scan of 194,756 matches for each of
them, because the matches table carries no index on either club column.

So one pass instead. Every match is read once and filed under both clubs,
and every figure this module returns - the table, the cards, the
superlatives - is a reduction of that one structure. A stat card can
therefore never disagree with the table beneath it, which is the failure
mode a second query would eventually produce.

WHAT A MATCH IS HERE. League matches only, which is the whole database:
there are no cup results on file. A match with a club this project cannot
resolve on either side is skipped rather than filed under a guessed
identity - 296 of 194,756, mostly clubs that appear once in a fifth-tier
season nobody else has heard from.

THE THRESHOLDS. "Best record" over three meetings is not a record, so the
superlatives that rank opponents are computed only over opponents met at
least MIN_MEETINGS times, and the rendered line names the number it used.
Where a club has no opponent that deep the floor drops to FLOOR_MEETINGS,
and where that also fails the lines are dropped rather than computed on a
handful of games. 251 of the 355 clubs clear the first threshold, 299 the
second; the remaining 56 are non-league clubs with four or five seasons on
file, and for them "we cannot say" is the honest output.
"""

from __future__ import annotations

import sqlite3

# Opponents met at least this often are eligible for the best/worst record
# lines; see the module docstring for why there are two numbers.
MIN_MEETINGS = 10
FLOOR_MEETINGS = 6

# "Never beaten by" is a weaker claim than a win rate, so it takes the
# lower bar - but not a bar of one, which would list every club met once.
UNBEATEN_MEETINGS = 6


def match_log(conn: sqlite3.Connection) -> dict[str, dict[str, list[dict]]]:
    """
    {club_id: {opponent_id: [match, ...]}}, newest first.

    A match dict is written from the reading club's side: goals_for,
    goals_against and venue, not home and away, because a table of a
    club's record is read from that club's point of view throughout.
    """
    # Feature-detected, as optional columns are everywhere else in this
    # codebase: a database built before match_date or division_id landed
    # still has to render, and a fixture built for one test certainly
    # does. The parts of the page that need the missing column say so
    # rather than the whole section vanishing.
    present = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
    if not present:                      # a database with no matches table
        return {}
    optional = [c for c in ("match_date", "tier", "division_id") if c in present]
    order = " ORDER BY season_end_year DESC"
    if "match_date" in present:
        order += ", match_date DESC"

    out: dict[str, dict[str, list[dict]]] = {}
    rows = conn.execute(
        "SELECT season_end_year, home_club_id, away_club_id, fthg, ftag"
        + "".join(f", {c}" for c in optional)
        + "  FROM matches"
        " WHERE home_club_id IS NOT NULL AND away_club_id IS NOT NULL"
        + order
    )
    for row in rows:
        season, home, away, hg, ag = row[:5]
        extra = dict(zip(optional, row[5:]))
        date = extra.get("match_date")
        tier = extra.get("tier")
        division_id = extra.get("division_id")
        if hg is None or ag is None:
            continue
        for club, opp, gf, ga, venue in (
            (home, away, hg, ag, "H"),
            (away, home, ag, hg, "A"),
        ):
            out.setdefault(club, {}).setdefault(opp, []).append({
                "season_end_year": season,
                "match_date": date,
                "tier": tier,
                "division_id": division_id,
                "goals_for": gf,
                "goals_against": ga,
                "venue": venue,
            })
    return out


def records(log: dict[str, list[dict]]) -> list[dict]:
    """
    One club's log to a row per opponent, most-played first.

    best_win and worst_defeat name a single match rather than a margin
    alone: "seven goals" is a fact about a scoreline, and a page that
    cannot say which scoreline is asking to be doubted.
    """
    out = []
    for opp, matches in log.items():
        won = drawn = lost = gf = ga = 0
        best = worst = None
        for m in matches:
            gf += m["goals_for"]
            ga += m["goals_against"]
            margin = m["goals_for"] - m["goals_against"]
            if margin > 0:
                won += 1
            elif margin == 0:
                drawn += 1
            else:
                lost += 1
            if best is None or margin > best["goals_for"] - best["goals_against"]:
                best = m
            if worst is None or margin < worst["goals_for"] - worst["goals_against"]:
                worst = m
        seasons = [m["season_end_year"] for m in matches]
        out.append({
            "opponent": opp,
            "played": len(matches),
            "won": won,
            "drawn": drawn,
            "lost": lost,
            "goals_for": gf,
            "goals_against": ga,
            "first_season": min(seasons),
            "last_season": max(seasons),
            "best": best,
            "worst": worst,
        })
    # Most-played first, then alphabetically by club_id so the order is the
    # same on every build rather than dict order.
    out.sort(key=lambda r: (-r["played"], r["opponent"]))
    return out


def threshold(rows: list[dict]) -> int | None:
    """The meeting count the best/worst lines are allowed to use, or None."""
    deepest = max((r["played"] for r in rows), default=0)
    if deepest >= MIN_MEETINGS:
        return MIN_MEETINGS
    if deepest >= FLOOR_MEETINGS:
        return FLOOR_MEETINGS
    return None


def summary(rows: list[dict]) -> dict:
    """
    The figures above the table: four totals, then the superlatives.

    Returns bare data - club ids, counts, matches. Naming and formatting
    are the site's business, and this module has no opinion about how a
    scoreline is written.
    """
    if not rows:
        return {}

    played = sum(r["played"] for r in rows)
    won = sum(r["won"] for r in rows)
    drawn = sum(r["drawn"] for r in rows)
    lost = sum(r["lost"] for r in rows)
    most = rows[0]                       # already sorted by meetings

    out = {
        "opponents": len(rows),
        "played": played,
        "won": won,
        "drawn": drawn,
        "lost": lost,
        "most_played": most,
        "threshold": threshold(rows),
        "best_record": None,
        "worst_record": None,
        "biggest_win": None,
        "heaviest_defeat": None,
        "never_beaten_by": [],
    }

    if out["threshold"] is not None:
        eligible = [r for r in rows if r["played"] >= out["threshold"]]
        # Ties broken by the deeper fixture, then by club id: a 100% record
        # over ten games says more than the same over the threshold itself.
        out["best_record"] = max(
            eligible, key=lambda r: (r["won"] / r["played"], r["played"],
                                     _reverse(r["opponent"])))
        out["worst_record"] = min(
            eligible, key=lambda r: (r["won"] / r["played"], -r["played"],
                                     r["opponent"]))

    def margin(m: dict) -> int:
        return m["goals_for"] - m["goals_against"]

    wins = [r for r in rows if margin(r["best"]) > 0]
    if wins:
        out["biggest_win"] = max(
            wins, key=lambda r: (margin(r["best"]),
                                 r["best"]["season_end_year"],
                                 _reverse(r["opponent"])))
    defeats = [r for r in rows if margin(r["worst"]) < 0]
    if defeats:
        out["heaviest_defeat"] = min(
            defeats, key=lambda r: (margin(r["worst"]),
                                    -r["worst"]["season_end_year"],
                                    r["opponent"]))

    out["never_beaten_by"] = [
        r for r in rows if r["lost"] == 0 and r["played"] >= UNBEATEN_MEETINGS
    ]
    return out


class _reverse:
    """Sort a string descending inside a key that sorts ascending."""

    __slots__ = ("value",)

    def __init__(self, value: str):
        self.value = value

    def __lt__(self, other) -> bool:
        return self.value > other.value

    def __eq__(self, other) -> bool:
        return self.value == other.value
