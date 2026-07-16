"""
Fetch and parse upcoming fixtures from football-data.co.uk.

The site publishes a single rolling fixtures.csv containing forthcoming
matches for all its leagues, keyed by the same Div codes as the results
files (E0..E3, EC), so Phase 1's name resolution applies unchanged.
"""

import datetime
import io
import logging

import pandas as pd
import requests
import urllib3

import entities

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"

DIV_TO_TIER = {"E0": 1, "E1": 2, "E2": 3, "E3": 4, "EC": 5}

DIV_TO_NAME = {
    "E0": "Premier League",
    "E1": "Championship",
    "E2": "League One",
    "E3": "League Two",
    "EC": "National League",
}


def current_season_end_year(today: datetime.date | None = None) -> int:
    """Seasons run Aug-May; from July onward we're in the season ending next year."""
    today = today or datetime.date.today()
    return today.year + 1 if today.month >= 7 else today.year


def parse_fixtures(
    df: pd.DataFrame,
    resolver: dict[str, str],
    today: datetime.date | None = None,
    window_days: int = 8,
) -> list[dict]:
    """
    Filter a raw fixtures DataFrame to our divisions within the next
    window_days, resolve club names, and return a list of fixture dicts
    sorted by tier then date. Pure function - testable without network.
    """
    today = today or datetime.date.today()
    season = current_season_end_year(today)

    required = {"Div", "Date", "HomeTeam", "AwayTeam"}
    missing = required - set(df.columns)
    if missing:
        logger.error("fixtures.csv missing columns: %s", missing)
        return []

    df = df[df["Div"].isin(DIV_TO_TIER)].copy()
    dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df[dates.notna()]
    if df.empty:
        return []
    df["_date"] = dates[dates.notna()].dt.date
    horizon = today + datetime.timedelta(days=window_days)
    df = df[(df["_date"] >= today) & (df["_date"] < horizon)]

    fixtures = []
    for _, row in df.iterrows():
        home_raw, away_raw = str(row["HomeTeam"]), str(row["AwayTeam"])
        fixtures.append({
            "div": row["Div"],
            "tier": DIV_TO_TIER[row["Div"]],
            "division_name": DIV_TO_NAME[row["Div"]],
            "date": row["_date"],
            "time": str(row["Time"]) if "Time" in df.columns and pd.notna(row.get("Time")) else "",
            "home_name": home_raw,
            "away_name": away_raw,
            "home_id": entities.resolve_name(home_raw, resolver, season),
            "away_id": entities.resolve_name(away_raw, resolver, season),
        })

    for f in fixtures:
        for side in ("home", "away"):
            if f[f"{side}_id"] is None:
                logger.warning(
                    "Unresolved fixture club name: %r (%s) — context will be limited",
                    f[f"{side}_name"], f["div"],
                )

    fixtures.sort(key=lambda f: (f["tier"], f["date"], f["home_name"]))
    return fixtures


def fetch_fixtures(
    resolver: dict[str, str],
    today: datetime.date | None = None,
    window_days: int = 8,
) -> list[dict]:
    """Download fixtures.csv and parse it. Returns [] on any failure."""
    try:
        resp = requests.get(FIXTURES_URL, timeout=30, verify=False)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Could not fetch fixtures.csv: %s", exc)
        return []

    try:
        df = pd.read_csv(io.BytesIO(resp.content), encoding="latin-1", on_bad_lines="skip")
    except Exception as exc:
        logger.error("Could not parse fixtures.csv: %s", exc)
        return []

    return parse_fixtures(df, resolver, today=today, window_days=window_days)
