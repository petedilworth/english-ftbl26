"""
What the reviews measure results against: each club's own record.

Two derived tables, dropped and rebuilt on every pipeline run:

club_streak_records - for every club and kind of run (win, loss, draw,
    unbeaten, winless, clean sheet, scoreless): the longest in the record,
    when it was, and the live run as of the club's latest match. "Within
    two games of the record" is then one comparison.

result_bands - for the latest season's matches, the results that mean
    something against that club's past: biggest win or heaviest defeat
    since a given season, first win over an opponent since, a run reaching
    a length not seen since, a best or worst start since. Each carries a
    band - historic (nothing like it in the record), notable (ten or more
    seasons since), of_note (five or more) - per docs/editions.md §7.

Runs are ordered by date, so only dated matches count towards them. The
historical backfill of the fifth tier and below carries whole seasons
without dates; a run stops at any season boundary where the club has an
undated season on either side, rather than pretending to know the order.
Margins and opponents need no order and use every match.

Points for the start-of-season comparison are 3-1-0 in every season,
including the 2-1-0 era before 1981/82, so a start in 1975 is compared
like for like with one today.
"""

import json
import logging
import sqlite3
from collections import defaultdict

import pandas as pd

logger = logging.getLogger(__name__)

STREAK_TYPES = ("win", "loss", "draw", "unbeaten", "winless", "clean_sheet", "scoreless")

# A run of one is not a run. Shorter kinds of run are noteworthy sooner.
STREAK_MIN_LENGTH = {"win": 3, "loss": 3, "draw": 3, "unbeaten": 5, "winless": 5,
                     "clean_sheet": 3, "scoreless": 3}

# A "start" is the first this many games. Below the floor every start is
# best-or-worst-since-something.
START_MIN_GAMES, START_MAX_GAMES = 5, 20

# Seasons since the last comparable thing, for each band.
NOTABLE_GAP, OF_NOTE_GAP = 10, 5

CREATE_STREAKS_SQL = """
CREATE TABLE club_streak_records (
    club_id                TEXT NOT NULL,
    streak_type            TEXT NOT NULL,
    record_length          INT,
    record_start_date      TEXT,
    record_end_date        TEXT,
    record_season_end_year INT,
    current_length         INT,
    current_start_date     TEXT,
    current_last_date      TEXT,
    -- the first dated season for the club: what "in their record" means
    since_season           INT,
    PRIMARY KEY (club_id, streak_type)
)
"""

CREATE_BANDS_SQL = """
CREATE TABLE result_bands (
    season_end_year INT NOT NULL,
    match_date      TEXT,
    tier            INT,
    home_club_id    TEXT,
    away_club_id    TEXT,
    club_id         TEXT NOT NULL,
    kind            TEXT NOT NULL,   -- margin | opponent | streak | start
    band            TEXT NOT NULL,   -- historic | notable | of_note
    since_season    INT,             -- the last comparable season; NULL for historic
    detail          TEXT             -- JSON, kind-specific
)
"""


# ── Loading ────────────────────────────────────────────────────────────────

def club_matches(conn: sqlite3.Connection) -> pd.DataFrame:
    """One row per club per match, both sides, oldest first. Unresolved clubs dropped."""
    home = pd.read_sql_query(
        """
        SELECT season_end_year AS season, match_date, tier,
               home_club_id AS club_id, away_club_id AS opp_id,
               fthg AS gf, ftag AS ga, 1 AS is_home,
               home_club_id, away_club_id
        FROM matches WHERE home_club_id IS NOT NULL AND away_club_id IS NOT NULL
        """, conn)
    away = home.rename(columns={"club_id": "opp_id", "opp_id": "club_id",
                                "gf": "ga", "ga": "gf"}).assign(is_home=0)
    df = pd.concat([home, away], ignore_index=True)
    df["dated"] = df["match_date"].notna()
    df["margin"] = df["gf"] - df["ga"]
    df["points"] = (df["margin"] > 0) * 3 + (df["margin"] == 0) * 1
    # Undated rows sort after dated ones within a season; they never enter
    # a run, but they are in the same frame so margins see them.
    df["sort_date"] = df["match_date"].fillna("9999-99-99")
    return df.sort_values(["club_id", "season", "sort_date"]).reset_index(drop=True)


def _flags(gf: int, ga: int) -> dict[str, bool]:
    return {"win": gf > ga, "loss": gf < ga, "draw": gf == ga,
            "unbeaten": gf >= ga, "winless": gf <= ga,
            "clean_sheet": ga == 0, "scoreless": gf == 0}


def band_for(gap: int | None, span: int) -> str | None:
    """
    gap: seasons since the last comparable thing, or None if there is none.
    span: seasons the club's record covers, so a club with three seasons
    on file does not get a "historic" every other week.
    """
    if gap is None:
        if span >= NOTABLE_GAP:
            return "historic"
        gap = span
    if gap >= NOTABLE_GAP:
        return "notable"
    if gap >= OF_NOTE_GAP:
        return "of_note"
    return None


# ── Streaks ────────────────────────────────────────────────────────────────

class _Run:
    __slots__ = ("length", "start", "last")

    def __init__(self):
        self.length, self.start, self.last = 0, None, None


def _streaks_for_club(rows: pd.DataFrame, undated_seasons: set[int],
                      latest_season: int):
    """
    Walk one club's dated matches in order. Returns the record and live
    run per type, and the bands earned by runs in the latest season.

    `completed` holds every run that ended, per type, so a run in the
    latest season can be compared with everything before it - not just
    the record - to say "longest since".
    """
    runs = {t: _Run() for t in STREAK_TYPES}
    record = {t: (0, None, None, None) for t in STREAK_TYPES}  # length, start, end, season
    completed: dict[str, list[tuple[int, int]]] = {t: [] for t in STREAK_TYPES}  # (length, end season)
    bands = []
    prev_season = None
    first_season = int(rows["season"].iloc[0])

    def close(t: str, season: int):
        r = runs[t]
        if r.length:
            completed[t].append((r.length, season))
        runs[t] = _Run()

    for row in rows.itertuples(index=False):
        season = int(row.season)
        if prev_season is not None and season != prev_season:
            # A run survives the summer only between consecutive, fully
            # dated seasons; otherwise the order of play is unknown.
            if not (season == prev_season + 1
                    and prev_season not in undated_seasons
                    and season not in undated_seasons):
                for t in STREAK_TYPES:
                    close(t, prev_season)
        prev_season = season

        flags = _flags(int(row.gf), int(row.ga))
        for t in STREAK_TYPES:
            r = runs[t]
            if flags[t]:
                if r.length == 0:
                    r.start = row.match_date
                r.length += 1
                r.last = row.match_date
                if r.length > record[t][0]:
                    record[t] = (r.length, r.start, r.last, season)
                if season == latest_season and r.length >= STREAK_MIN_LENGTH[t]:
                    prior = [s for length, s in completed[t] if length >= r.length]
                    since = max(prior) if prior else None
                    if since != season:  # a longer run earlier this season is not news
                        gap = None if since is None else season - since
                        b = band_for(gap, season - first_season)
                        if b:
                            bands.append((row, t, r.length, b, since))
            else:
                close(t, season)
    return record, runs, bands, first_season


def _add_band(out: list, row, club_id: str, kind: str, band: str,
              since: int | None, detail: dict) -> None:
    out.append((int(row.season), row.match_date if isinstance(row.match_date, str) else None,
                int(row.tier), row.home_club_id, row.away_club_id, club_id,
                kind, band, since, json.dumps(detail)))


# ── Margins, opponents, starts ─────────────────────────────────────────────

def _margin_bands(rows: pd.DataFrame, latest: pd.DataFrame, first_season: int, out: list):
    """Biggest win or heaviest defeat since. Every match counts, dated or not."""
    club_id = rows["club_id"].iloc[0]
    for row in latest.itertuples(index=False):
        m = int(row.margin)
        if m == 0:
            continue
        # Earlier seasons, plus dated earlier matches this season.
        before = rows[(rows["season"] < row.season)
                      | ((rows["season"] == row.season) & rows["dated"]
                         & (rows["sort_date"] < row.sort_date))]
        comparable = before[before["margin"] >= m] if m > 0 else before[before["margin"] <= m]
        if not comparable.empty:
            since = int(comparable["season"].max())
            if since == row.season:
                continue
            gap = int(row.season) - since
        else:
            since, gap = None, None
        b = band_for(gap, int(row.season) - first_season)
        if b:
            _add_band(out, row, club_id, "margin", b, since,
                      {"direction": "win" if m > 0 else "defeat", "margin": abs(m),
                       "score": f"{int(row.gf)}-{int(row.ga)}", "opp_id": row.opp_id})


def _opponent_bands(rows: pd.DataFrame, latest: pd.DataFrame, first_season: int, out: list):
    """First win over this opponent since. Needs a few earlier meetings to mean anything."""
    club_id = rows["club_id"].iloc[0]
    for row in latest.itertuples(index=False):
        if row.margin <= 0:
            continue
        before = rows[(rows["opp_id"] == row.opp_id)
                      & ((rows["season"] < row.season)
                         | ((rows["season"] == row.season) & rows["dated"]
                            & (rows["sort_date"] < row.sort_date)))]
        if len(before) < 4:
            continue
        wins = before[before["margin"] > 0]
        if not wins.empty:
            since = int(wins["season"].max())
            if since == row.season:
                continue
            gap = int(row.season) - since
            span = int(row.season) - int(before["season"].min())
        else:
            since, gap = None, None
            span = int(row.season) - int(before["season"].min())
        b = band_for(gap, span)
        if b:
            _add_band(out, row, club_id, "opponent", b, since,
                      {"opp_id": row.opp_id, "meetings_before": int(len(before)),
                       "score": f"{int(row.gf)}-{int(row.ga)}"})


def _start_bands(rows: pd.DataFrame, latest_season: int, undated_seasons: set[int],
                 first_dated_season: int, out: list):
    """Best or worst start since: points after n games against every earlier season."""
    club_id = rows["club_id"].iloc[0]
    dated = rows[rows["dated"] & ~rows["season"].isin(undated_seasons)]
    if dated.empty:
        return
    # points after n games, per season
    table: dict[int, list[int]] = {}
    for season, grp in dated.groupby("season"):
        table[int(season)] = grp["points"].cumsum().astype(int).tolist()
    this = table.get(latest_season)
    if not this:
        return
    current = dated[dated["season"] == latest_season]
    for n, (row, pts) in enumerate(zip(current.itertuples(index=False), this), start=1):
        if n < START_MIN_GAMES or n > START_MAX_GAMES:
            continue
        earlier = {s: p[n - 1] for s, p in table.items() if s < latest_season and len(p) >= n}
        if not earlier:
            continue
        for direction, cmp in (("best", lambda p: p >= pts), ("worst", lambda p: p <= pts)):
            matching = [s for s, p in earlier.items() if cmp(p)]
            since = max(matching) if matching else None
            gap = None if since is None else latest_season - since
            b = band_for(gap, latest_season - first_dated_season)
            if b:
                _add_band(out, row, club_id, "start", b, since,
                          {"direction": direction, "games": n, "points": int(pts)})


# ── Rebuild ────────────────────────────────────────────────────────────────

def rebuild_records(conn: sqlite3.Connection) -> None:
    df = club_matches(conn)
    conn.execute("DROP TABLE IF EXISTS club_streak_records")
    conn.execute("DROP TABLE IF EXISTS result_bands")
    conn.execute(CREATE_STREAKS_SQL)
    conn.execute(CREATE_BANDS_SQL)
    if df.empty:
        conn.commit()
        return

    latest_season = int(df["season"].max())
    streak_rows: list[tuple] = []
    band_rows: list[tuple] = []

    for club_id, rows in df.groupby("club_id", sort=False):
        undated_seasons = set(rows.loc[~rows["dated"], "season"].astype(int))
        dated = rows[rows["dated"]]
        first_season_any = int(rows["season"].min())
        latest = rows[(rows["season"] == latest_season) & rows["dated"]]

        if not dated.empty:
            record, live, sbands, first_dated = _streaks_for_club(
                dated, undated_seasons, latest_season)
            last_date = dated["match_date"].iloc[-1]
            for t in STREAK_TYPES:
                length, start, end, season = record[t]
                r = live[t]
                streak_rows.append((club_id, t, length, start, end, season,
                                    r.length, r.start, last_date if r.length else None,
                                    first_dated))
            for row, t, length, b, since in sbands:
                _add_band(band_rows, row, club_id, "streak", b, since,
                          {"streak_type": t, "length": length})
            if not latest.empty:
                _start_bands(rows, latest_season, undated_seasons, first_dated, band_rows)

        if not latest.empty:
            _margin_bands(rows, latest, first_season_any, band_rows)
            _opponent_bands(rows, latest, first_season_any, band_rows)

    conn.executemany(
        "INSERT INTO club_streak_records VALUES (?,?,?,?,?,?,?,?,?,?)", streak_rows)
    conn.executemany(
        "INSERT INTO result_bands VALUES (?,?,?,?,?,?,?,?,?,?)", band_rows)
    conn.commit()
    logger.info("Rebuilt club_streak_records (%d rows) and result_bands (%d rows for %d)",
                len(streak_rows), len(band_rows), latest_season)
