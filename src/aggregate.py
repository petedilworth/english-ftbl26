"""
Read raw match-level CSVs and aggregate to league standings.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Early seasons used HG/AG instead of FTHG/FTAG
COLUMN_ALIASES = {"HG": "FTHG", "AG": "FTAG"}

REQUIRED_COLS = {"HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"}

DIVISION_NAMES: dict = {
    1: {range(1959, 1993): "First Division",
        range(1993, 9999): "Premier League"},
    2: {range(1959, 1993): "Second Division",
        range(1993, 2004): "First Division", range(2004, 9999): "Championship"},
    3: {range(1959, 1993): "Third Division",
        range(1993, 2004): "Second Division", range(2004, 9999): "League One"},
    4: {range(1959, 1993): "Fourth Division",
        range(1993, 2004): "Third Division", range(2004, 9999): "League Two"},
    5: {range(2006, 2016): "Conference Premier", range(2016, 9999): "National League"},
}

# The Football League awarded two points for a win until 1980/81 and three
# from 1981/82. Every points figure on this site - records, survival
# thresholds, the tables themselves - depends on getting this right for the
# season it belongs to, and a single global "3" quietly inflates every
# pre-1982 season by roughly a third.
THREE_POINTS_FROM = 1982


def points_for_win(season_end_year: int) -> int:
    return 3 if season_end_year >= THREE_POINTS_FROM else 2


def points_rule(tier: int, season_end_year: int) -> tuple[int, int, int]:
    """
    Points for a home win, an away win and a draw.

    Almost everywhere this is (2, 2, 1) or (3, 3, 1) and the venue is
    irrelevant. The exception is the Alliance Premier League, which for
    three seasons from 1983/84 tried paying more for winning away from
    home: two points for a home win, three for an away one. It is the only
    time an English national division has valued the two differently, and
    ignoring it does not merely shift totals - it changes who won. Under a
    flat three-for-a-win, 1984/85 comes out as Bath City; the away-win rule
    reproduces the published table exactly, Wealdstone 62 and Nuneaton 58.

    Verified by computing all 26 Alliance/Conference seasons and checking
    the champion against the documented record: 24 of 26 agree, and the
    two that don't are source errors rather than rule errors (see
    historical.TIER5_CHAMPIONS).
    """
    if tier == 5 and 1984 <= season_end_year <= 1986:
        return (2, 3, 1)
    win = points_for_win(season_end_year)
    return (win, win, 1)


def tiebreak_rule(tier: int, season_end_year: int) -> str:
    """
    How clubs level on points are separated, which has changed twice.

    Points are not the only era-dependent rule in an English league table.
    The tiebreak has run through three regimes, and getting it wrong does
    not merely reorder mid-table - it changes who is recorded as champion.

    - To 1975/76 the Football League used goal average, goals scored
      divided by goals conceded. A club could score fewer and concede
      fewer and still finish above.
    - From 1976/77 it used goal difference.
    - From 1992/93 to 1998/99 the Football League put goals scored ahead
      of goal difference, reverting for 1999/2000. The Premier League,
      formed in 1992, used goal difference throughout and never adopted
      it, so in those seasons the rule reaches tiers 2-4 only. The
      Conference is not the Football League and is not covered either.

    The case that proves it: in 1996/97 Wigan Athletic and Fulham both
    finished the Third Division on 87 points. Fulham had the better goal
    difference, +34 to +33; Wigan had scored more, 84 to 72. Under the
    rule in force Wigan were champions. Ranking that table by goal
    difference hands the title to Fulham, which is not what happened.
    """
    if season_end_year <= 1976:
        return "goal_average"
    if 1993 <= season_end_year <= 1999 and 2 <= tier <= 4:
        return "goals_scored"
    return "goal_difference"

# Expected minimum matches per season (used for incomplete-season detection)
EXPECTED_MATCHES = {
    20: 380,  # 20-club league
    22: 462,  # 22-club PL 1992-95
    24: 552,  # 24-club league
}


def expected_match_count(n_teams: int) -> int:
    """Total matches a completed season of this size should contain."""
    return EXPECTED_MATCHES.get(n_teams, n_teams * (n_teams - 1))


def get_division_name(tier: int, season_end_year: int) -> str:
    tier_map = DIVISION_NAMES.get(tier, {})
    for yr_range, name in tier_map.items():
        if season_end_year in yr_range:
            return name
    return f"Tier {tier}"


def load_csv(path: Path) -> pd.DataFrame | None:
    """Load and normalise a raw CSV. Returns None on failure."""
    if not path.exists() or path.stat().st_size < 10:
        logger.warning("Missing or empty file: %s", path)
        return None

    # football-data.co.uk's older files are ragged: some rows carry MORE
    # fields than the header declares - extra trailing odds columns present
    # for that particular fixture but not for every match that season - and
    # a handful carry fewer. on_bad_lines used to be the bare string "skip",
    # which dropped either kind with no word about it, and for years that
    # meant real, played matches vanishing with no trace: a 2002/03 League
    # Two file with all 552 matches present on disk still produced a table
    # with 217 missing, because 217 rows had a stray extra column.
    #
    # A too-wide row is recoverable: every column this pipeline actually
    # reads - Div, Date, HomeTeam, AwayTeam, FTHG, FTAG, FTR - sits within
    # the header's own declared width in every football-data schema this
    # project has seen, so trimming the row to that width keeps the match
    # and only discards odds data nothing here uses. A too-narrow row is
    # genuinely missing data and still can't be recovered.
    with open(path, "rb") as fh:
        header_width = len(fh.readline().decode("latin-1").rstrip("\r\n").split(","))

    for encoding in ("utf-8", "latin-1", "cp1252"):
        skipped: list[list] = []
        counts = {"truncated": 0}

        def _on_bad_line(bad, _acc=skipped, _counts=counts):
            if len(bad) > header_width:
                _counts["truncated"] += 1
                return bad[:header_width]
            _acc.append(bad)
            return None

        try:
            df = pd.read_csv(
                path,
                encoding=encoding,
                engine="python",
                on_bad_lines=_on_bad_line,
            )
            break
        except Exception as exc:
            logger.debug("Encoding %s failed for %s: %s", encoding, path.name, exc)
    else:
        logger.error("Could not read %s", path)
        return None

    if counts["truncated"]:
        logger.info(
            "%s: %d row(s) had more fields than the header declares (extra "
            "trailing columns, commonly odds data not used here) - trimmed "
            "to fit rather than dropped",
            path.name, counts["truncated"],
        )
    if skipped:
        logger.warning(
            "%s: %d malformed row(s) skipped by the CSV parser - these are "
            "matches that will be missing from the table. First: %.120s",
            path.name, len(skipped), skipped[0],
        )

    # Normalise column aliases
    df.rename(columns=COLUMN_ALIASES, inplace=True)

    # Drop completely empty rows (common at end of some CSVs)
    df.dropna(how="all", inplace=True)

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        logger.warning("Missing columns %s in %s — skipping", missing, path.name)
        return None

    # Deduplicate
    date_col = "Date" if "Date" in df.columns else None
    dedup_cols = (
        ["HomeTeam", "AwayTeam", date_col] if date_col else ["HomeTeam", "AwayTeam"]
    )
    before = len(df)
    df.drop_duplicates(subset=dedup_cols, inplace=True)
    dropped = before - len(df)
    if dropped:
        logger.warning("Dropped %d duplicate rows from %s", dropped, path.name)

    # Keep only valid results
    before = len(df)
    df = df[df["FTR"].isin({"H", "A", "D"})].copy()
    invalid = before - len(df)
    if invalid:
        logger.info("Filtered %d rows with invalid FTR from %s", invalid, path.name)

    if df.empty:
        logger.warning("No valid rows in %s", path.name)
        return None

    return df


def rank_standings(
    standings: pd.DataFrame,
    tier: int | None = None,
    season_end_year: int | None = None,
) -> pd.DataFrame:
    """
    Order a table and number its positions.

    Split out of compute_standings so it can be re-run after points
    deductions have been applied: a deduction changes the points a club
    finished on, and therefore where it finished. Doing it in this order
    is the whole point - it makes the ordinary positional promotion and
    relegation rules produce the right answer without anything having to
    know a sanction happened.

    tier and season_end_year select the era's tiebreak - see tiebreak_rule.
    Omitting them falls back to goal difference, which is correct for every
    season from 1999/2000 on.
    """
    rule = (
        tiebreak_rule(tier, season_end_year)
        if tier is not None and season_end_year is not None
        else "goal_difference"
    )
    if rule == "goal_average":
        # Conceding nothing across a season does not happen, but guard it
        # rather than divide by zero on a partial table.
        standings = standings.assign(
            _tiebreak=standings["gf"] / standings["ga"].where(standings["ga"] != 0, 1)
        )
        keys = ["points", "_tiebreak", "gf"]
    elif rule == "goals_scored":
        keys = ["points", "gf", "gd"]
    else:
        keys = ["points", "gd", "gf"]

    standings = standings.sort_values(
        keys, ascending=[False] * len(keys)
    ).reset_index(drop=True)
    standings = standings.drop(columns=["_tiebreak"], errors="ignore")
    if "position" in standings.columns:
        standings = standings.drop(columns=["position"])
    standings.insert(0, "position", standings.index + 1)
    return standings


def compute_standings(
    df: pd.DataFrame,
    season_end_year: int,
    tier: int,
) -> pd.DataFrame:
    """Aggregate match rows to a standings table."""
    records = []

    all_teams = set(df["HomeTeam"]).union(set(df["AwayTeam"]))

    for team in sorted(all_teams):
        home = df[df["HomeTeam"] == team]
        away = df[df["AwayTeam"] == team]

        hw = (home["FTR"] == "H").sum()
        hd = (home["FTR"] == "D").sum()
        hl = (home["FTR"] == "A").sum()
        aw = (away["FTR"] == "A").sum()
        ad = (away["FTR"] == "D").sum()
        al = (away["FTR"] == "H").sum()

        w = hw + aw
        d = hd + ad
        l = hl + al
        played = w + d + l
        gf = int(home["FTHG"].sum()) + int(away["FTAG"].sum())
        ga = int(home["FTAG"].sum()) + int(away["FTHG"].sum())
        gd = gf - ga
        home_win_pts, away_win_pts, draw_pts = points_rule(tier, season_end_year)
        pts = hw * home_win_pts + aw * away_win_pts + d * draw_pts

        records.append(
            {
                "club_name": team,
                "played": played,
                "won": w,
                "drawn": d,
                "lost": l,
                "gf": gf,
                "ga": ga,
                "gd": gd,
                "points": pts,
            }
        )

    standings = rank_standings(pd.DataFrame(records), tier, season_end_year)

    # Incomplete season warning
    n_teams = len(standings)
    expected = expected_match_count(n_teams)
    if len(df) < expected * 0.5:
        logger.warning(
            "%s/%s: only %d matches found, expected ~%d — possible incomplete season",
            season_end_year,
            tier,
            len(df),
            expected,
        )

    standings["season_end_year"] = season_end_year
    standings["tier"] = tier
    standings["division_name"] = get_division_name(tier, season_end_year)

    return standings[
        [
            "season_end_year",
            "tier",
            "division_name",
            "club_name",
            "position",
            "played",
            "won",
            "drawn",
            "lost",
            "gf",
            "ga",
            "gd",
            "points",
        ]
    ]


def extract_matches(
    df: pd.DataFrame,
    season_end_year: int,
    tier: int,
) -> pd.DataFrame:
    """
    Return one row per match from a loaded CSV: date (ISO or None),
    home/away raw names, goals, result. Feeds the matches table used for
    head-to-head and recent-form lookups.
    """
    out = df[["HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]].copy()
    if "Date" in df.columns:
        dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        # A date outside the season it is filed under is not a date we can
        # use. The tier-5 source carries the calendar year of the following
        # season across the August-December block of 2000/01 and 2001/02,
        # which would otherwise put a September fixture nine months after
        # the final. The season the file is for is authoritative; a date
        # that contradicts it is dropped rather than trusted, leaving the
        # result intact and only the date unknown.
        season_start = pd.Timestamp(year=season_end_year - 1, month=7, day=1)
        season_stop = pd.Timestamp(year=season_end_year, month=8, day=31)
        plausible = dates.between(season_start, season_stop)
        dropped = int((dates.notna() & ~plausible).sum())
        if dropped:
            logger.warning(
                "%d/%d: %d match date(s) fall outside the season and were "
                "dropped; results kept", season_end_year, tier, dropped)
        dates = dates.where(plausible)
        out["match_date"] = dates.dt.strftime("%Y-%m-%d")
        out["match_date"] = out["match_date"].where(dates.notna(), None)
    else:
        out["match_date"] = None
    out["season_end_year"] = season_end_year
    out["tier"] = tier
    return out


def aggregate_season(
    path: Path,
    season_end_year: int,
    tier: int,
) -> pd.DataFrame | None:
    """Load CSV and compute standings. Returns None on failure."""
    df = load_csv(path)
    if df is None:
        return None
    try:
        return compute_standings(df, season_end_year, tier)
    except Exception as exc:
        logger.error("Failed aggregating %s: %s", path.name, exc)
        return None
