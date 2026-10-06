"""
The rest of each football-data.co.uk row: the betting odds and the match
statistics, which the standings never needed and the pipeline used to
throw away.

Odds start around 2000/01 and the shot counts with them for tiers 1-4;
the fifth tier has odds from 2005/06 and patchier statistics. Which
bookmakers appear changes over the years, so three odds sets are kept:

- the market: the site's own average (AvgH, from 2019/20), else the
  Betbrain average (BbAvH, 2005/06-2018/19), else the mean of every
  bookmaker in the row, which is all the earliest seasons offer;
- closing: the market average at kick-off (AvgCH), else Pinnacle's
  closing price, both from 2019/20 or thereabouts;
- Pinnacle and Bet365 on their own, the sharpest price and the most
  common one.

Nothing is derived here. src/luck.py turns odds into probabilities.

Columns: see notes at https://www.football-data.co.uk/notes.txt.
"""

import logging
import math
import sqlite3

import pandas as pd

logger = logging.getLogger(__name__)

# Every bookmaker prefix that has appeared in an English file. Each is
# followed by H, D and A.
BOOKMAKERS = ["B365", "BW", "BS", "GB", "IW", "LB", "PS", "P", "SO", "SB", "SJ", "SY", "VC", "WH"]

# Stored name -> football-data column.
STATS = {
    "ht_hg": "HTHG", "ht_ag": "HTAG",
    "home_shots": "HS", "away_shots": "AS",
    "home_sot": "HST", "away_sot": "AST",
    "home_corners": "HC", "away_corners": "AC",
    "home_fouls": "HF", "away_fouls": "AF",
    "home_yellow": "HY", "away_yellow": "AY",
    "home_red": "HR", "away_red": "AR",
}

ODDS_SETS = ["mkt", "close", "pin", "b365"]
ODDS_COLUMNS = [f"{s}_{o}" for s in ODDS_SETS for o in ("h", "d", "a")]

CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS match_stats (
    season_end_year INT  NOT NULL,
    tier            INT  NOT NULL,
    division_id     TEXT,
    match_date      TEXT,
    home_club_id    TEXT,
    away_club_id    TEXT,
    home_name       TEXT NOT NULL,
    away_name       TEXT NOT NULL,
    {", ".join(f"{c} REAL" for c in ODDS_COLUMNS)},
    mkt_books       INT,
    {", ".join(f"{c} INT" for c in STATS)},
    referee         TEXT
);
"""

COLUMNS = (["season_end_year", "tier", "division_id", "match_date", "home_club_id", "away_club_id",
            "home_name", "away_name"] + ODDS_COLUMNS + ["mkt_books"] + list(STATS) + ["referee"])


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(math.nan, index=df.index)
    return pd.to_numeric(df[col], errors="coerce")


def _odds(df: pd.DataFrame, prefix: str, suffix: str = "") -> pd.DataFrame:
    """H/D/A odds for one bookmaker, NaN unless all three are real prices."""
    out = pd.DataFrame({o: _num(df, f"{prefix}{suffix}{o.upper()}") for o in ("h", "d", "a")})
    ok = (out > 1).all(axis=1)
    return out.where(ok)


def _first(*frames: pd.DataFrame) -> pd.DataFrame:
    """Row by row, the first frame with a full set of prices."""
    out = frames[0].copy()
    for f in frames[1:]:
        gap = out.isna().any(axis=1)
        out.loc[gap] = f.loc[gap].values
    return out


def market(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """
    The market's price per match, and how many bookmakers it rests on
    (None where the file's own average is used, since it does not say).
    """
    books = [_odds(df, b) for b in BOOKMAKERS]
    stacked = pd.concat({b: f for b, f in zip(BOOKMAKERS, books)}, axis=1)
    mean = pd.DataFrame({o: stacked.xs(o, axis=1, level=1).mean(axis=1) for o in ("h", "d", "a")})
    count = pd.concat([f["h"].notna() for f in books], axis=1).sum(axis=1)
    avg = _first(_odds(df, "Avg"), _odds(df, "BbAv"))
    n = count.where(avg.isna().any(axis=1))
    return _first(avg, mean), n


def extract(df: pd.DataFrame) -> pd.DataFrame:
    """One row per match with odds and statistics, indexed like df."""
    out = pd.DataFrame(index=df.index)
    mkt, n = market(df)
    sets = {
        "mkt": mkt,
        "close": _first(_odds(df, "Avg", "C"), _odds(df, "PS", "C")),
        "pin": _first(_odds(df, "PS"), _odds(df, "P")),
        "b365": _odds(df, "B365"),
    }
    for s, frame in sets.items():
        for o in ("h", "d", "a"):
            out[f"{s}_{o}"] = frame[o].round(3)
    out["mkt_books"] = n
    for name, col in STATS.items():
        out[name] = _num(df, col)
    if "Referee" in df.columns:
        ref = df["Referee"].astype("string").str.strip()
        out["referee"] = ref.where(ref.notna() & (ref != ""), None)
    else:
        out["referee"] = None
    return out


def has_anything(row: pd.Series) -> bool:
    return any(pd.notna(row[c]) for c in ODDS_COLUMNS + list(STATS) + ["referee"])


def rows_for(match_df: pd.DataFrame, matches: pd.DataFrame, season_end_year: int, tier: int,
             division_id, resolve) -> list[tuple]:
    """
    The match_stats rows for one season file. `matches` is
    aggregate.extract_matches' frame, so dates agree with the matches table;
    `resolve` maps a raw name to a club_id.
    """
    stats = extract(match_df)
    rows = []
    for idx, m in matches.iterrows():
        s = stats.loc[idx]
        if not has_anything(s):
            continue
        rows.append(tuple(
            [season_end_year, tier, division_id, m["match_date"], resolve(m["HomeTeam"]), resolve(m["AwayTeam"]),
             m["HomeTeam"], m["AwayTeam"]]
            + [float(s[c]) if pd.notna(s[c]) else None for c in ODDS_COLUMNS]
            + [int(s["mkt_books"]) if pd.notna(s["mkt_books"]) else None]
            + [int(s[c]) if pd.notna(s[c]) else None for c in STATS]
            + [str(s["referee"]) if pd.notna(s["referee"]) else None]))
    return rows


def replace(conn: sqlite3.Connection, season_end_year: int, tier: int, division_id, rows: list[tuple]) -> None:
    """Replace one division-season, keyed the same way as matches."""
    conn.execute(CREATE_SQL)
    conn.execute(
        "DELETE FROM match_stats WHERE season_end_year = ? AND tier = ?"
        " AND (division_id = ? OR (division_id IS NULL AND ? IS NULL))",
        (season_end_year, tier, division_id, division_id))
    if rows:
        conn.executemany(
            f"INSERT INTO match_stats ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})", rows)
