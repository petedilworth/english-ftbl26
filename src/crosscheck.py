"""
Check the standings we computed against an independent record of the same
seasons, and say so when they disagree.

This exists because of what the 1993/94 overlap turned up. Backfilling
tiers 1-4 from engsoccerdata gave two sources for that season, and three of
the four divisions matched exactly. The fourth did not: football-data.co.uk
had Bristol Rovers 2-5 Barnet on 26 March 1994, where two independent
sources both have Bristol Rovers 5-2 Barnet. One transposed scoreline had
been sitting in the database for as long as the database existed, quietly
moving three points and six goals between two clubs, and nothing here could
have noticed - a wrong result is still a well-formed result.

Widening that check found ten division-seasons in the same shape,
clustered in the years where football-data.co.uk's files are thinnest.

The comparison is deliberately blunt. Club names differ between sources
("Hull" against "Hull City"), and so does the order of clubs level on
points, so neither is used: what gets compared is the multiset of
(on-pitch points, goal difference) pairs in a division. That is invariant
to naming and to tie-breaking, and it still catches any result that
actually differs.

Two adjustments matter for the comparison to mean anything. Points
deductions are added back, because the reference records the sanction
separately and a table that has already had ten points removed is not
comparable to one that hasn't. And divisions already flagged incomplete
are skipped, since a table missing fixtures is expected to disagree.

This never fails a run. It is advisory: the reference is a third-party
file that may be unreachable, may lag a season, and is not automatically
more right than we are. It reports, and a human decides.
"""

from __future__ import annotations

import collections
import csv
import logging
import sqlite3
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

SOURCE_URL = (
    "https://raw.githubusercontent.com/jfjelstul/englishfootball/master/"
    "data-csv/standings.csv"
)
SOURCE_NAME = "jfjelstul/englishfootball"
CACHE_NAME = "reference_standings.csv"

# The reference covers tiers 1-4 only, and ends before the current season.
# Anything outside that is simply unchecked, which the summary says.
COVERED_TIERS = (1, 2, 3, 4)


def fetch_reference(raw_dir: Path, force: bool = False,
                    session: requests.Session | None = None) -> Path | None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / CACHE_NAME
    if path.exists() and path.stat().st_size > 100_000 and not force:
        return path
    logger.info("Downloading reference standings from %s", SOURCE_NAME)
    try:
        get = (session or requests).get
        response = get(SOURCE_URL, timeout=120)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Cross-check skipped: could not fetch reference (%s)", exc)
        return None
    path.write_bytes(response.content)
    return path


def _load_reference(path: Path) -> dict[tuple[int, int], collections.Counter]:
    """
    {(season_end_year, tier): Counter of (on-pitch points, goal difference)}.

    The reference's `points` already has its `point_adjustment` applied, so
    subtracting it back out gives what the clubs earned on the pitch, which
    is what our standings hold before deductions are applied.
    """
    table: dict[tuple[int, int], collections.Counter] = collections.defaultdict(
        collections.Counter)
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                tier = int(row["tier"])
                if tier not in COVERED_TIERS:
                    continue
                # 'season' is the year the season began.
                season = int(row["season"]) + 1
                played = int(row["played"])
                points = int(row["points"]) - int(row["point_adjustment"] or 0)
                gd = int(row["goal_difference"])
            except (KeyError, TypeError, ValueError):
                continue
            if not played:
                # Clubs whose record was expunged survive in the reference as
                # a nil row. They played no matches, so they belong in no
                # comparison of what was played.
                continue
            table[(season, tier)][(points, gd)] += 1
    return table


def _load_ours(conn: sqlite3.Connection) -> dict[tuple[int, int], collections.Counter]:
    table: dict[tuple[int, int], collections.Counter] = collections.defaultdict(
        collections.Counter)
    rows = conn.execute(
        """
        SELECT season_end_year, tier, points, gd, COALESCE(points_deducted, 0)
        FROM standings
        WHERE tier IN (1, 2, 3, 4)
          AND COALESCE(data_complete, 1) = 1
          AND status != 'In progress'
          AND played > 0
        """
    ).fetchall()
    for season, tier, points, gd, deducted in rows:
        table[(season, tier)][(points + deducted, gd)] += 1
    return table


def compare(conn: sqlite3.Connection, reference_csv: Path) -> list[dict]:
    """
    Return one entry per division-season that disagrees with the reference,
    each with the count of club-seasons involved.
    """
    reference = _load_reference(reference_csv)
    ours = _load_ours(conn)

    findings = []
    checked = 0
    for key in sorted(ours):
        if key not in reference:
            continue
        checked += 1
        theirs, mine = reference[key], ours[key]
        if mine == theirs:
            continue
        findings.append({
            "season_end_year": key[0],
            "tier": key[1],
            "clubs": sum((mine - theirs).values()),
            "ours": sorted(mine - theirs),
            "reference": sorted(theirs - mine),
        })

    unchecked = len(ours) - checked
    logger.info(
        "Cross-check: %d division-seasons compared against %s, %d unchecked "
        "(outside its tiers 1-4 or its season range)",
        checked, SOURCE_NAME, unchecked,
    )
    return findings


def run(conn: sqlite3.Connection, raw_dir: Path, force: bool = False,
        session: requests.Session | None = None) -> list[dict]:
    """
    Fetch the reference and report disagreements. Advisory only - a
    unreachable reference or a disagreement never fails the pipeline.
    """
    path = fetch_reference(raw_dir, force=force, session=session)
    if path is None:
        return []

    findings = compare(conn, path)
    if not findings:
        logger.info("Cross-check: every comparable division-season agrees")
        return findings

    total = sum(f["clubs"] for f in findings)
    logger.warning(
        "Cross-check: %d division-season(s) disagree with %s, %d club-season(s) "
        "affected - most often one match with a different scoreline",
        len(findings), SOURCE_NAME, total,
    )
    for f in findings:
        logger.warning(
            "  %d/%02d tier %d: %d club-season(s) differ; ours %s, reference %s",
            f["season_end_year"] - 1, f["season_end_year"] % 100, f["tier"],
            f["clubs"],
            ", ".join(f"{p}pts {g:+d}" for p, g in f["ours"]),
            ", ".join(f"{p}pts {g:+d}" for p, g in f["reference"]),
        )
    return findings
