"""
A club for everyone: the allocation.

A visitor gives a date of birth and is assigned a club. Nothing about it
needs any knowledge of football, which is the point: the rest of the site
assumes a reader who already has a club, and most people do not.

THE RULE, in full, because a process nobody can check is a horoscope:

  1. Count the days from the first day of the record to the day of birth.
  2. Take the league table as it stood at the end of that day - every club
     in the top four divisions, top to bottom, ninety-two of them in all
     but one season.
  3. Divide the day count by the number of clubs. The remainder, counted
     down from the top, is a place in that table. The club in it is yours.

So consecutive birthdays walk down the table a place at a time, everyone
born on one day gets one club, and over any three months every place is
handed out. It is arbitrary and it is fair, and it can be done by hand.

THE TABLE ON A DAY. Every match in the top four divisions is dated from
23 August 1958, so the table for any day since is the results up to it,
ranked under that season's own rules (aggregate.points_rule and
aggregate.tiebreak_rule: two points for a win, then three; goal average,
then goal difference, with goals scored first for a while in between).
Two things are deliberately not attempted:

  - Points deductions are not applied mid-season. The record holds how
    many points a club lost and in which season, not on which day, and a
    table that guessed would be wrong for part of every such season.
  - Once a season's last match has been played the table is not computed
    at all: it is the final table from the standings, which has the
    deductions in, the curtailed seasons settled on points per game, and
    every other correction the pipeline has ever made. A birthday in June
    gets the table everyone remembers.

BEFORE THE RECORD. Someone born before 23 August 1958 predates every
match here. They get the same day of the year in the record's first
season instead, and the notice says so.

WHERE IT RUNS. In the browser, not here: the date never leaves the
visitor's device, which is the only promise a page that asks for a date
of birth should make. static/allocation.js does the arithmetic on the
season files this module writes. The functions below are the same
arithmetic in Python - the reference the tests hold the script to - so
the two cannot drift without a test saying so.
"""

import datetime
import sqlite3

import aggregate

# The Football League and the Premier League: "the ninety-two". The fifth
# tier is in the record from 1979/80 but its matches are only dated from
# 1999, so a table on a day cannot be made for it before then.
LEAGUE_TIERS = (1, 2, 3, 4)

TIEBREAK_CODE = {"goal_average": "ga", "goals_scored": "gs", "goal_difference": "gd"}

IN_PROGRESS = "In progress"


def _has(conn: sqlite3.Connection, table: str, *columns: str) -> bool:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    return bool(cols) and all(c in cols for c in columns)


def available(conn: sqlite3.Connection) -> bool:
    """Whether this database can run the process at all: dated matches between known clubs."""
    if not _has(conn, "matches", "match_date", "home_club_id", "away_club_id", "tier"):
        return False
    return bool(conn.execute(
        "SELECT 1 FROM matches WHERE tier <= 4 AND match_date IS NOT NULL"
        " AND home_club_id IS NOT NULL LIMIT 1").fetchone())


def _iso(d) -> str:
    return d.isoformat() if isinstance(d, datetime.date) else str(d)


def _date(s) -> datetime.date:
    return s if isinstance(s, datetime.date) else datetime.date.fromisoformat(str(s)[:10])


# ── What the browser is given ─────────────────────────────────────────────

def index(conn: sqlite3.Connection) -> dict | None:
    """
    The small file the page loads first: where the record starts, and which
    season a date falls in. A season runs from its first match day to the
    day before the next one's, so the summer belongs to the season that
    has just ended.
    """
    if not available(conn):
        return None
    tiers = ",".join(str(t) for t in LEAGUE_TIERS)
    spans = conn.execute(
        f"SELECT season_end_year, MIN(match_date), MAX(match_date) FROM matches"
        f" WHERE tier IN ({tiers}) AND match_date IS NOT NULL"
        f" GROUP BY season_end_year ORDER BY season_end_year").fetchall()
    live = {r[0] for r in conn.execute(
        "SELECT DISTINCT season_end_year FROM standings WHERE status = ?", (IN_PROGRESS,))}
    seasons = [[s, first, last, 0 if s in live else 1] for s, first, last in spans]
    if not seasons:
        return None
    return {"epoch": seasons[0][1], "latest": seasons[-1][2], "seasons": seasons}


def season_data(conn: sqlite3.Connection, season: int) -> dict | None:
    """
    One season as the browser needs it: the clubs in final order, the
    rules, the final table where there is one, and every dated match.

    Clubs are listed tier by tier in their finishing order, so a club's
    number is also its place in the final table and nothing has to be
    looked up twice. Matches are five numbers each - day, home, away and
    the score - the day counted from the season's first.
    """
    tiers = ",".join(str(t) for t in LEAGUE_TIERS)
    rows = conn.execute(
        f"SELECT tier, club_id, club_name, division_name, position, played, won, drawn, lost, gf, ga, points, status"
        f" FROM standings WHERE season_end_year = ? AND tier IN ({tiers}) AND club_id IS NOT NULL"
        f" ORDER BY tier, position, club_name", (season,)).fetchall()
    if not rows:
        return None
    clubs = [r[1] for r in rows]
    number = {club: i for i, club in enumerate(clubs)}
    tiers_present, sizes, divisions, rules = [], [], [], []
    for tier in LEAGUE_TIERS:
        members = [r for r in rows if r[0] == tier]
        if not members:
            continue
        tiers_present.append(tier)
        sizes.append(len(members))
        divisions.append(members[0][3] or aggregate.get_division_name(tier, season))
        home, away, draw = aggregate.points_rule(tier, season)
        rules.append([home, away, draw, TIEBREAK_CODE[aggregate.tiebreak_rule(tier, season)]])
    complete = not any(r[12] == IN_PROGRESS for r in rows)

    matches = conn.execute(
        f"SELECT match_date, home_club_id, away_club_id, fthg, ftag FROM matches"
        f" WHERE season_end_year = ? AND tier IN ({tiers}) AND match_date IS NOT NULL"
        f" AND fthg IS NOT NULL AND ftag IS NOT NULL ORDER BY match_date, home_club_id", (season,)).fetchall()
    # A match involving a club with no standings row cannot be placed in a
    # table; none exist in the top four divisions, and one that appeared
    # would be a data fault to find, not to crash on.
    matches = [m for m in matches if m[1] in number and m[2] in number]
    if not matches:
        return None
    first = _date(matches[0][0])
    flat: list[int] = []
    for when, home, away, hg, ag in matches:
        flat.extend([(_date(when) - first).days, number[home], number[away], int(hg), int(ag)])
    out = {
        "season": season, "first": first.isoformat(), "last": _iso(_date(matches[-1][0])),
        "complete": complete, "clubs": clubs, "tiers": tiers_present, "sizes": sizes,
        "divisions": divisions, "rules": rules, "m": flat,
    }
    if complete:
        out["final"] = [[r[5] or 0, r[6] or 0, r[7] or 0, r[8] or 0, r[9] or 0, r[10] or 0, r[11] or 0]
                        for r in rows]
    return out


# ── The arithmetic (mirrored in static/allocation.js) ─────────────────────

def season_for(idx: dict, date: datetime.date) -> int | None:
    """The season a date belongs to; None before the record begins."""
    found = None
    for season, first, _last, _complete in idx["seasons"]:
        if _date(first) <= date:
            found = season
        else:
            break
    return found


def stand_in(idx: dict, date: datetime.date) -> datetime.date:
    """
    For a birth before the record: the same day of the year in the record's
    first season. 29 February has no such day in 1959 and takes the 28th.
    """
    epoch = _date(idx["epoch"])
    for year in (epoch.year, epoch.year + 1):
        day = date.day
        while True:
            try:
                candidate = datetime.date(year, date.month, day)
                break
            except ValueError:
                day -= 1
        if candidate >= epoch:
            return candidate
    return epoch


def _sort_key(rule_code: str, row: dict):
    """Descending on each part; the caller negates. Mirrors aggregate.rank_standings."""
    if rule_code == "ga":
        return (row["points"], row["gf"] / (row["ga"] or 1), row["gf"])
    if rule_code == "gs":
        return (row["points"], row["gf"], row["gf"] - row["ga"])
    return (row["points"], row["gf"] - row["ga"], row["gf"])


def table(data: dict, date: datetime.date, names: dict[str, str] | None = None) -> list[dict]:
    """
    The top four divisions as they stood at the end of `date`, as a list of
    {tier, division, final, rows}. Each row carries the club's number in
    the season file, so the caller can go straight to its name.

    From a season's last match day on, in a finished season, this is the
    final table as recorded. Before that it is the results so far, ranked
    under the season's rules; clubs level on everything stay in name order,
    which is the order aggregate.rank_standings leaves them in.
    """
    names = names or {}
    first = _date(data["first"])
    day = (date - first).days
    use_final = data.get("complete") and "final" in data and date >= _date(data["last"])
    n = len(data["clubs"])
    stats = [{"club": i, "played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "points": 0}
             for i in range(n)]
    tier_of = []
    for t, size in enumerate(data["sizes"]):
        tier_of.extend([t] * size)

    if use_final:
        for i, (p, w, d, lost, gf, ga, pts) in enumerate(data["final"]):
            stats[i].update(played=p, won=w, drawn=d, lost=lost, gf=gf, ga=ga, points=pts)
    else:
        m = data["m"]
        for k in range(0, len(m), 5):
            when, home, away, hg, ag = m[k:k + 5]
            if when > day:
                break  # matches are in date order
            win_home, win_away, draw, _code = data["rules"][tier_of[home]]
            h, a = stats[home], stats[away]
            h["played"] += 1; a["played"] += 1
            h["gf"] += hg; h["ga"] += ag; a["gf"] += ag; a["ga"] += hg
            if hg > ag:
                h["won"] += 1; a["lost"] += 1; h["points"] += win_home
            elif hg < ag:
                a["won"] += 1; h["lost"] += 1; a["points"] += win_away
            else:
                h["drawn"] += 1; a["drawn"] += 1; h["points"] += draw; a["points"] += draw

    out, start = [], 0
    for t, size in enumerate(data["sizes"]):
        members = stats[start:start + size]
        if not use_final:
            code = data["rules"][t][3]
            # Name order first, then a stable sort on the ranking: clubs the
            # rules cannot separate stay alphabetical.
            members = sorted(members, key=lambda r: names.get(data["clubs"][r["club"]], data["clubs"][r["club"]]))
            members = sorted(members, key=lambda r: tuple(-x for x in _sort_key(code, r)))
        rows = [dict(r, position=i + 1) for i, r in enumerate(members)]
        out.append({"tier": data["tiers"][t], "division": data["divisions"][t], "final": bool(use_final),
                    "rows": rows})
        start += size
    return out


def allocate(idx: dict, data: dict, born: datetime.date, names: dict[str, str] | None = None) -> dict:
    """
    The club for a date of birth, with the working shown.

    `data` must be the season file for the date the process used - the
    birth date, or its stand-in for someone born before the record (see
    process_date). Returns the day count, the number of clubs, the place
    and the club, and the table it was read from.
    """
    used = process_date(idx, born)
    divisions = table(data, used, names)
    order = [(d, r) for d in divisions for r in d["rows"]]
    n = len(order)
    day = (used - _date(idx["epoch"])).days
    place = day % n
    division, row = order[place]
    return {
        "born": born.isoformat(), "used": used.isoformat(), "stand_in": born < _date(idx["epoch"]),
        "day": day, "clubs": n, "place": place + 1,
        "club": data["clubs"][row["club"]], "tier": division["tier"], "division": division["division"],
        "position": row["position"], "row": row, "table": divisions,
    }


def match_on(data: dict, date: datetime.date, club: str) -> dict:
    """
    What a club did on the day itself: how many league matches were played
    that day, and its own if it had one, as {home, opponent, f, a}. This is
    where the notice's most quotable sentence comes from - "they lost 6-0
    away to Crystal Palace that day" - so it is checked against the
    matches table like everything else.
    """
    day = (date - _date(data["first"])).days
    number = data["clubs"].index(club)
    played, mine = 0, None
    m = data["m"]
    for k in range(0, len(m), 5):
        when, home, away, hg, ag = m[k:k + 5]
        if when > day:
            break
        if when != day:
            continue
        played += 1
        if home == number:
            mine = {"home": True, "opponent": data["clubs"][away], "f": hg, "a": ag}
        if away == number:
            mine = {"home": False, "opponent": data["clubs"][home], "f": ag, "a": hg}
    return {"played": played, "match": mine}


def process_date(idx: dict, born: datetime.date) -> datetime.date:
    """The date the process actually uses: the birth date, clamped into the record at both ends."""
    if born < _date(idx["epoch"]):
        return stand_in(idx, born)
    return min(born, _date(idx["latest"]))


def run(conn: sqlite3.Connection, born: datetime.date) -> dict | None:
    """The whole process against a database, for tests and for the curious at a prompt."""
    idx = index(conn)
    if not idx:
        return None
    used = process_date(idx, born)
    data = season_data(conn, season_for(idx, used))
    if not data:
        return None
    names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))
    return allocate(idx, data, born, names)


def allocatable(conn: sqlite3.Connection) -> list[str]:
    """Every club the process can hand out: those with a season in the top four divisions."""
    tiers = ",".join(str(t) for t in LEAGUE_TIERS)
    return [r[0] for r in conn.execute(
        f"SELECT DISTINCT club_id FROM standings WHERE tier IN ({tiers}) AND club_id IS NOT NULL ORDER BY club_id")]
