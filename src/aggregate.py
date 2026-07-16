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
    1: {range(1994, 9999): "Premier League"},
    2: {range(1994, 2004): "First Division", range(2004, 9999): "Championship"},
    3: {range(1994, 2004): "Second Division", range(2004, 9999): "League One"},
    4: {range(1994, 2004): "Third Division", range(2004, 9999): "League Two"},
    5: {range(2006, 2016): "Conference Premier", range(2016, 9999): "National League"},
}

# Expected minimum matches per season (used for incomplete-season detection)
EXPECTED_MATCHES = {
    20: 380,  # 20-club league
    22: 462,  # 22-club PL 1992-95
    24: 552,  # 24-club league
}


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

    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(path, encoding=encoding, on_bad_lines="skip")
            break
        except Exception as exc:
            logger.debug("Encoding %s failed for %s: %s", encoding, path.name, exc)
    else:
        logger.error("Could not read %s", path)
        return None

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
        pts = w * 3 + d

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

    standings = pd.DataFrame(records)
    standings.sort_values(
        ["points", "gd", "gf"], ascending=[False, False, False], inplace=True
    )
    standings.reset_index(drop=True, inplace=True)
    standings.insert(0, "position", standings.index + 1)

    # Incomplete season warning
    n_teams = len(standings)
    expected = EXPECTED_MATCHES.get(n_teams, n_teams * (n_teams - 1))
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
