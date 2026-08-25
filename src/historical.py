"""
Backfill tiers 1-4 before 1993/94, where football-data.co.uk's files begin.

The source is engsoccerdata (github.com/jalapic/engsoccerdata), an open
dataset of every English league match from 1888. It is match-level, which
matters: the standings here are always computed from results rather than
transcribed from a published table, and keeping that true for the older
seasons means head-to-head records and form work across the whole range
instead of stopping at an arbitrary year.

Two boundaries decide the range this module covers.

1958/59 is the floor, and it is a structural one rather than a preference.
Before it the third tier was two regional divisions, Third Division North
and Third Division South, which the rest of this codebase has nowhere to
put - every tier here is one division. The source labels them '3N' and
'3S', so the boundary is visible in the data itself and this module simply
refuses to cross it.

1992/93 is the ceiling because football-data.co.uk takes over at 1993/94.
The two sources overlap there, which is worth more than it sounds: the
overlap is what `crosscheck.py` uses to verify one against the other.

Rather than teach the pipeline a second CSV dialect, this converts to the
football-data column shape and writes files the existing ingest already
understands. The only difference is the filename suffix, which keeps the
provenance recorded honestly in standings.source rather than crediting
football-data.co.uk with seasons it never published.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import requests

import download

logger = logging.getLogger(__name__)

_BASE = "https://raw.githubusercontent.com/jalapic/engsoccerdata/master/data-raw"
SOURCE_URL = f"{_BASE}/england.csv"
SOURCE_NAME = "engsoccerdata"
CACHE_NAME = "engsoccerdata_england.csv"

# The same project publishes tier 5 separately, from the Alliance Premier
# League's first season.
TIER5_SOURCE_URL = f"{_BASE}/england5.csv"
TIER5_CACHE_NAME = "engsoccerdata_england5.csv"

# 1958/59, the first season the third and fourth tiers were national.
FIRST_SEASON = 1959
# 1992/93. football-data.co.uk owns 1993/94 onward.
LAST_SEASON = 1993

# 1979/80, the Alliance Premier League's first season and the first time
# English football had a national fifth tier at all. Nothing below the
# Football League was national before it, so this is a real floor rather
# than a limit of the source.
TIER5_FIRST_SEASON = 1980
# 2004/05. football-data.co.uk's EC files begin at 2005/06.
TIER5_LAST_SEASON = 2005

TIERS = (1, 2, 3, 4)

# Every Alliance Premier League / Football Conference champion, as a
# permanent check on the source rather than as data we publish.
#
# Tier 5 has no second machine-readable source to cross-check against -
# crosscheck.py's reference covers tiers 1-4 only - so this list is the
# check. Computing all 26 seasons and comparing the winner catches both a
# wrong points rule and a wrong result, which is how the two bad seasons
# below were found. Names are matched loosely, since the source spells
# several clubs differently ("Stevenage Borough", "Rushden & Diamonds").
TIER5_CHAMPIONS: dict[int, str] = {
    1980: "Altrincham",      1981: "Altrincham",     1982: "Runcorn",
    1983: "Enfield",         1984: "Maidstone",      1985: "Wealdstone",
    1986: "Enfield",         1987: "Scarborough",    1988: "Lincoln",
    1989: "Maidstone",       1990: "Darlington",     1991: "Barnet",
    1992: "Colchester",      1993: "Wycombe",        1994: "Kidderminster",
    1995: "Macclesfield",    1996: "Stevenage",      1997: "Macclesfield",
    1998: "Halifax",         1999: "Cheltenham",     2000: "Kidderminster",
    2001: "Rushden",         2002: "Boston",         2003: "Yeovil",
    2004: "Chester",         2005: "Barnet",
}

# The two seasons where the source disagrees with the published table badly
# enough to change who won. Both are flagged not-final on ingest, which
# keeps them off every records table and puts a note on the table itself.
# They are still shown: a club's path through those years is real even
# where the order of the table is not.
TIER5_UNRELIABLE: dict[int, str] = {
    1991: ("the source has Colchester United top on 85 points; Barnet won "
           "the title on a published 87, and come out on 82 here"),
    1992: ("the source has Wycombe Wanderers top by a point; Colchester "
           "United won the title"),
}

# Division-seasons after 1992/93 where football-data.co.uk is demonstrably
# wrong and this source is right.
#
# These were found by comparing every division-season we hold against an
# independent record (see crosscheck.py). In each case the two independent
# sources agree with each other and football-data.co.uk is the outlier, so
# the season is taken from here instead. The list is deliberately explicit
# rather than a date range: it is a set of known errors with evidence
# behind each, not a judgement that one source is generally better.
#
# Adding to it should mean the cross-check flagged something and a human
# confirmed which side is right.
OVERRIDES: dict[tuple[int, int], str] = {
    (1994, 3): "26 Mar 1994 Bristol Rovers v Barnet transposed as 2-5",
    (1995, 3): "one scoreline differs; affects Oxford, Hull, Blackpool, Wrexham",
    (1995, 4): "one scoreline differs; affects Carlisle and Barnet",
    (1996, 2): "one scoreline differs; affects Crystal Palace and Huddersfield",
    (1996, 3): "one scoreline differs; affects Notts County and York",
    (1996, 4): "one scoreline differs; affects Scunthorpe, Fulham, Lincoln, Scarborough",
    (1997, 2): "one scoreline differs; affects Tranmere, Man City, Grimsby, Southend",
    (1997, 3): "one scoreline differs; affects Wrexham and Wycombe",
    (2000, 4): "one scoreline differs; affects Hartlepool and Rochdale",
    (2013, 3): "one scoreline differs; affects Shrewsbury and Portsmouth",
}

# The regional third-tier labels. Their presence in a row is the signal
# that we have reached the era this model cannot represent.
REGIONAL_DIVISIONS = {"3N", "3S"}


def fetch_source(raw_dir: Path, force: bool = False,
                 session: requests.Session | None = None,
                 url: str = SOURCE_URL, cache_name: str = CACHE_NAME,
                 min_bytes: int = 1_000_000) -> Path | None:
    """
    Download a source dataset once and cache it. These cover seasons long
    since played and never change, so a cached copy stays valid and
    re-fetching is only ever useful when the file is damaged.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / cache_name
    if path.exists() and path.stat().st_size > min_bytes and not force:
        logger.debug("Already cached: %s", path.name)
        return path

    logger.info("Downloading %s", url)
    try:
        get = (session or requests).get
        response = get(url, timeout=120)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Could not fetch %s: %s", url, exc)
        return None

    path.write_bytes(response.content)
    logger.info("Saved %s (%.1f MB)", path.name, len(response.content) / 1e6)
    return path


def _iso_to_uk(value: str) -> str:
    """
    ISO date to football-data's DD/MM/YYYY. The loader parses dates with
    dayfirst=True, so emitting the shape it already expects avoids relying
    on that flag being ignored for unambiguous ISO strings.
    """
    parts = (value or "").split("-")
    if len(parts) != 3:
        return ""
    year, month, day = parts
    return f"{day}/{month}/{year}"


def convert(
    source: Path,
    raw_dir: Path,
    first_season: int = FIRST_SEASON,
    last_season: int = LAST_SEASON,
    force: bool = False,
    tiers: tuple[int, ...] = TIERS,
) -> list[Path]:
    """
    Split the source into one football-data-shaped CSV per season and tier.

    Returns the paths written. A season already on disk is left alone
    unless force is set, so a re-run costs nothing.
    """
    if tiers == TIERS and first_season < FIRST_SEASON:
        raise ValueError(
            f"{first_season} is before {FIRST_SEASON}: the third tier was "
            f"regional (3N/3S) until 1958/59 and this model holds one "
            f"division per tier"
        )

    buckets: dict[tuple[int, int], list[dict]] = {}
    regional_seen = 0
    with open(source, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            # 'Season' is the year the season began; everything here is
            # keyed on the year it ended.
            try:
                season_end = int(row["Season"]) + 1
                tier = int(row["tier"])
            except (KeyError, TypeError, ValueError):
                continue
            in_range = first_season <= season_end <= last_season
            if not (in_range or (season_end, tier) in OVERRIDES):
                continue
            if row.get("division") in REGIONAL_DIVISIONS:
                regional_seen += 1
                continue
            if tier not in tiers:
                continue
            buckets.setdefault((season_end, tier), []).append(row)

    if regional_seen:
        # Only reachable if the floor is ever lowered by hand.
        logger.warning(
            "Skipped %d matches in regional Third Division North/South, "
            "which this model has no tier for", regional_seen
        )

    written: list[Path] = []
    for (season_end, tier), rows in sorted(buckets.items()):
        path = raw_dir / historical_filename(season_end, tier)
        if path.exists() and not force:
            written.append(path)
            continue
        with open(path, "w", encoding="utf-8", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(["Div", "Date", "HomeTeam", "AwayTeam",
                             "FTHG", "FTAG", "FTR"])
            for row in rows:
                writer.writerow([
                    download.TIER_TO_CODE[tier],
                    _iso_to_uk(row.get("Date", "")),
                    row["home"], row["visitor"],
                    row["hgoal"], row["vgoal"], row["result"],
                ])
        written.append(path)
        logger.debug("Wrote %s (%d matches)", path.name, len(rows))

    logger.info("Prepared %d historical division-seasons (%d-%d, tiers 1-4)",
                len(written), first_season, last_season)
    return written


def historical_filename(season_end_year: int, tier: int) -> str:
    """
    The football-data filename plus a marker. The marker is what lets the
    pipeline record where a season actually came from - without it these
    files are indistinguishable from downloads and standings.source would
    credit football-data.co.uk with seasons it never published.
    """
    season_str = download.season_to_str(season_end_year)
    return f"{season_str}_E{tier - 1}_hist.csv"


def source_label(season_end_year: int, tier: int) -> str:
    season_str = download.season_to_str(season_end_year)
    return f"{SOURCE_NAME}/{download.TIER_TO_CODE[tier]}/{season_str}"


def backfill(
    raw_dir: Path,
    first_season: int = FIRST_SEASON,
    last_season: int = LAST_SEASON,
    force: bool = False,
    session: requests.Session | None = None,
) -> list[Path]:
    """Fetch the tiers 1-4 source if needed and write the per-season files."""
    source = fetch_source(raw_dir, force=force, session=session)
    if source is None:
        logger.error("Historical backfill skipped: source unavailable")
        return []
    return convert(source, raw_dir, first_season, last_season, force=force)


def backfill_tier5(
    raw_dir: Path,
    first_season: int = TIER5_FIRST_SEASON,
    last_season: int = TIER5_LAST_SEASON,
    force: bool = False,
    session: requests.Session | None = None,
) -> list[Path]:
    """Same, for the Alliance Premier League / Conference."""
    source = fetch_source(
        raw_dir, force=force, session=session,
        url=TIER5_SOURCE_URL, cache_name=TIER5_CACHE_NAME, min_bytes=100_000,
    )
    if source is None:
        logger.error("Tier 5 backfill skipped: source unavailable")
        return []
    return convert(source, raw_dir, first_season, last_season,
                   force=force, tiers=(5,))


def check_tier5_champions(conn) -> list[int]:
    """
    Compare each backfilled tier-5 season's winner against the documented
    record, and return the seasons that disagree.

    This is the only verification tier 5 gets - crosscheck.py's reference
    stops at tier 4 - so it runs on every pipeline pass rather than being a
    one-off. A season that starts disagreeing after previously agreeing
    means the upstream file changed under us.
    """
    wrong = []
    for season, expected in sorted(TIER5_CHAMPIONS.items()):
        row = conn.execute(
            "SELECT club_name FROM standings"
            " WHERE season_end_year = ? AND tier = 5 AND position = 1",
            (season,),
        ).fetchone()
        if row is None:
            continue
        if expected.lower() not in row[0].lower():
            wrong.append(season)
            logger.warning(
                "Tier 5 %d/%02d: computed champion is %s, but %s won it",
                season - 1, season % 100, row[0], expected,
            )
    if wrong:
        logger.warning(
            "%d tier-5 season(s) disagree with the documented champion and "
            "are flagged not-final", len(wrong))
    else:
        logger.info("Tier 5: all %d backfilled champions match the record",
                    len(TIER5_CHAMPIONS))
    return wrong
