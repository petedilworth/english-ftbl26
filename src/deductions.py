"""
Points deductions: the one thing in a league table that didn't happen on
the pitch.

standings.points is computed as wins*3 + draws from match results, and a
sporting sanction - administration, a financial-rules breach, an ineligible
player - never appears in a result. So without this the stored total is the
pre-deduction one for every club that was ever docked, and the table is
wrong in a way nothing downstream can detect: Wigan Athletic sit 13th in
2019/20 on 59 points, marked relegated, because they were docked 12.

Deductions are therefore data, not derivation. They live in
points_deductions.csv, keyed on club_id and the season whose table the
points actually came off - which is frequently NOT the season of the
offence. A club entering administration in the close season serves the
penalty the following year (Bournemouth 2008/09, Bolton 2019/20), and a
sanction can be handed down years later against whichever table the club
happens to be in (Sheffield United 2024/25).

Suspended penalties are recorded with applied = 0. They are part of the
story and belong in the file, but they never reached a table and must
never be subtracted.
"""

import logging
import sqlite3
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"club_id", "season_end_year", "tier", "points", "applied"}

CREATE_POINTS_DEDUCTIONS_SQL = """
CREATE TABLE IF NOT EXISTS points_deductions (
    club_id         TEXT NOT NULL,
    season_end_year INT  NOT NULL,
    tier            INT,
    points          INT  NOT NULL,
    category        TEXT,
    applied         INT  NOT NULL DEFAULT 1,
    reason          TEXT,
    source_url      TEXT,
    note            TEXT
);
"""

COLUMNS = [
    "club_id", "season_end_year", "tier", "points", "category",
    "applied", "reason", "source_url", "note",
]

# A club can be docked more than once in a season - Derby County took 12
# for administration and 9 for accounting breaches in 2021/22, and
# Macclesfield Town collected four separate sanctions in 2019/20 - so
# there is deliberately no primary key on (club_id, season).


def _int(value, field: str) -> int | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        logger.warning("points_deductions: %s is not a number: %r", field, value)
        return None


def _validate(row: dict, club_ids: set[str]) -> list[str]:
    problems = []
    if row["club_id"] not in club_ids:
        problems.append(f"unknown club_id {row['club_id']!r}")
    if row["season_end_year"] is None:
        problems.append("missing season_end_year")
    if row["points"] is None:
        problems.append("missing points")
    elif row["points"] <= 0:
        # Deductions are recorded as a positive number of points removed;
        # a negative would silently award points instead.
        problems.append(f"points must be positive, got {row['points']}")
    if row["applied"] not in (0, 1):
        problems.append(f"applied must be 0 or 1, got {row['applied']!r}")
    if not row.get("source_url"):
        problems.append("no source_url")
    return problems


def seed_points_deductions(conn: sqlite3.Connection, csv_path: Path) -> int:
    """
    Create points_deductions (if absent) and load the CSV, which is the
    single source of truth - the table is replaced wholesale.

    A row that fails validation is skipped with a warning rather than
    raising. A deduction that can't be trusted is worse than a missing
    one: it would silently rewrite a league table.
    """
    conn.execute(CREATE_POINTS_DEDUCTIONS_SQL)
    conn.commit()

    if not csv_path.exists():
        logger.info("No %s - points_deductions left empty", csv_path.name)
        return 0

    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"{csv_path.name} missing columns: {sorted(missing)}")

    club_ids = {r[0] for r in conn.execute("SELECT club_id FROM club_master")}

    rows, skipped = [], 0
    for _, raw in df.iterrows():
        row = {col: str(raw.get(col, "")).strip() for col in COLUMNS}
        row["season_end_year"] = _int(row["season_end_year"], "season_end_year")
        row["tier"] = _int(row["tier"], "tier")
        row["points"] = _int(row["points"], "points")
        row["applied"] = _int(row["applied"], "applied")

        problems = _validate(row, club_ids)
        if problems:
            logger.warning(
                "points_deductions: skipping %s %s - %s",
                row["club_id"], row["season_end_year"], "; ".join(problems),
            )
            skipped += 1
            continue
        rows.append(tuple(row[c] or None if c not in
                          ("season_end_year", "tier", "points", "applied")
                          else row[c] for c in COLUMNS))

    conn.execute("DELETE FROM points_deductions")
    placeholders = ",".join("?" * len(COLUMNS))
    conn.executemany(
        f"INSERT INTO points_deductions ({','.join(COLUMNS)})"
        f" VALUES ({placeholders})",
        rows,
    )
    conn.commit()

    if skipped:
        logger.warning("points_deductions: %d row(s) skipped as unusable", skipped)
    logger.info("points_deductions: loaded %d row(s)", len(rows))
    return len(rows)


def applied_by_club_season(conn: sqlite3.Connection) -> dict[tuple[str, int], int]:
    """
    {(club_id, season_end_year): total points removed}, applied rows only.

    Several sanctions in one season are summed: Derby's 12 + 9, and
    Macclesfield's 4 + 7 + 2 + 4.
    """
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='points_deductions'"
    ).fetchone():
        return {}

    totals: dict[tuple[str, int], int] = {}
    for club_id, season, points in conn.execute(
        "SELECT club_id, season_end_year, points FROM points_deductions"
        " WHERE applied = 1"
    ):
        totals[(club_id, season)] = totals.get((club_id, season), 0) + points
    return totals
