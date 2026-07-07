"""
End-to-end pipeline: download CSVs → aggregate standings → resolve clubs
→ assign status → persist to SQLite → rebuild trajectory.

Usage:
    python src/pipeline.py [options]

Options:
    --skip-download       Skip the download step (use cached CSVs only)
    --force-download      Re-download CSVs even if they already exist
    --season-start YEAR   First season end year to process (default: 1994)
    --season-end   YEAR   Last season end year to process (default: current year)
    --db-path PATH        Path to SQLite file (default: data/db/england.db)
    --raw-dir PATH        Directory for raw CSVs (default: data/raw)
"""

import argparse
import datetime
import logging
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# Ensure src/ is importable regardless of cwd
_SRC = Path(__file__).parent
sys.path.insert(0, str(_SRC))

import aggregate
import download
import entities
import status
import trajectory

PROJECT_ROOT = Path(__file__).parent.parent

CREATE_STANDINGS_SQL = """
CREATE TABLE IF NOT EXISTS standings (
    season_end_year  INT  NOT NULL,
    tier             INT  NOT NULL,
    division_name    TEXT,
    club_id          TEXT,
    club_name        TEXT NOT NULL,
    position         INT,
    played           INT,
    won              INT,
    drawn            INT,
    lost             INT,
    gf               INT,
    ga               INT,
    gd               INT,
    points           INT,
    status           TEXT,
    source           TEXT,
    UNIQUE(season_end_year, tier, club_name),
    FOREIGN KEY (club_id) REFERENCES club_master(club_id)
);
"""

STANDINGS_STAT_COLUMNS = ["played", "won", "drawn", "lost", "gf", "ga", "gd"]


def _migrate_standings_columns(conn: sqlite3.Connection) -> None:
    """Add stat columns to standings tables created before they existed."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(standings)")}
    for col in STANDINGS_STAT_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE standings ADD COLUMN {col} INT")
            logger.info("Migrated standings table: added column %s", col)
    conn.commit()

logger = logging.getLogger(__name__)

_FILENAME_RE = re.compile(r"^(\d{4})_E(\d)\.csv$")


def _parse_filename(filename: str) -> tuple[int, int] | None:
    """Return (season_end_year, tier) from a filename like '9394_E0.csv', or None."""
    m = _FILENAME_RE.match(filename)
    if not m:
        return None
    season_str, tier_digit = m.group(1), int(m.group(2))
    tier = tier_digit + 1
    season_end_year = download.str_to_season(season_str)
    return season_end_year, tier


def _build_source(season_end_year: int, tier: int) -> str:
    code = download.TIER_TO_CODE[tier]
    season_str = download.season_to_str(season_end_year)
    return f"football-data.co.uk/{code}/{season_str}"


def _process_season(
    conn: sqlite3.Connection,
    csv_path: Path,
    season_end_year: int,
    tier: int,
    resolver: dict,
    unresolved_map: dict,
) -> int:
    """
    Aggregate one season CSV, assign status, resolve names, insert into standings.
    Returns count of rows inserted.
    """
    standings_df = aggregate.aggregate_season(csv_path, season_end_year, tier)
    if standings_df is None:
        return 0

    standings_df = status.assign_status(standings_df, season_end_year, tier)
    source = _build_source(season_end_year, tier)

    rows = []
    for _, row in standings_df.iterrows():
        raw_name = row["club_name"]
        club_id = entities.resolve_name(raw_name, resolver, season_end_year)
        if club_id is None:
            key = f"{season_end_year}/E{tier - 1}"
            unresolved_map[raw_name].append(key)

        rows.append((
            int(row["season_end_year"]),
            int(row["tier"]),
            row["division_name"],
            club_id,
            raw_name,
            int(row["position"]),
            int(row["played"]),
            int(row["won"]),
            int(row["drawn"]),
            int(row["lost"]),
            int(row["gf"]),
            int(row["ga"]),
            int(row["gd"]),
            int(row["points"]),
            row["status"],
            source,
        ))

    try:
        conn.executemany(
            """
            INSERT OR REPLACE INTO standings
                (season_end_year, tier, division_name, club_id, club_name,
                 position, played, won, drawn, lost, gf, ga, gd,
                 points, status, source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("Failed inserting %d/%d: %s", season_end_year, tier, exc)
        return 0

    return len(rows)


def _reconcile_statuses(conn: sqlite3.Connection) -> None:
    """
    Correct positional status assignments using observed movement.

    Play-off positions mark eligibility, but only the winner goes up; a club's
    actual tier next season is ground truth. Rows for the latest season, and
    clubs with no row the following season (folded or dropped below Tier 5),
    keep their positional status.
    """
    pairs = conn.execute(
        """
        SELECT s.rowid, s.club_id, s.season_end_year, s.tier, s.status, n.tier
        FROM standings s
        JOIN standings n
          ON n.club_id = s.club_id
         AND n.season_end_year = s.season_end_year + 1
        WHERE s.club_id IS NOT NULL
        """
    ).fetchall()

    updates: list[tuple[str, int]] = []
    for rowid, club_id, season, tier, status_val, next_tier in pairs:
        moved_up = next_tier < tier
        moved_down = next_tier > tier

        if status_val == "Play-off Promoted" and not moved_up:
            updates.append(("Stayed", rowid))
        elif status_val == "Promoted" and not moved_up:
            logger.warning(
                "%s marked Promoted in %d (tier %d) but did not move up — "
                "setting Stayed (check RULES)", club_id, season, tier)
            updates.append(("Stayed", rowid))
        elif status_val in ("Relegated", "Play-off Relegated") and not moved_down:
            logger.warning(
                "%s marked %s in %d (tier %d) but did not move down — "
                "setting Stayed (reprieve or RULES gap)",
                club_id, status_val, season, tier)
            updates.append(("Stayed", rowid))
        elif status_val == "Stayed" and moved_up:
            logger.warning(
                "%s marked Stayed in %d (tier %d) but moved up — "
                "setting Promoted (check RULES)", club_id, season, tier)
            updates.append(("Promoted", rowid))
        elif status_val == "Stayed" and moved_down:
            logger.warning(
                "%s marked Stayed in %d (tier %d) but moved down — "
                "setting Relegated (check RULES)", club_id, season, tier)
            updates.append(("Relegated", rowid))

    if updates:
        conn.executemany("UPDATE standings SET status = ? WHERE rowid = ?", updates)
        conn.commit()
    logger.info("Status reconciliation: %d rows corrected", len(updates))


def _print_unresolved_report(unresolved_map: dict[str, list[str]]) -> None:
    if not unresolved_map:
        print("\nAll club names resolved successfully.")
        return

    total_rows = sum(len(v) for v in unresolved_map.values())
    print("\n=== UNRESOLVED CLUB NAMES ===")
    for name, appearances in sorted(unresolved_map.items()):
        locs = ", ".join(appearances[:5])
        if len(appearances) > 5:
            locs += f" (+{len(appearances) - 5} more)"
        print(f'  "{name}"  →  appeared in {locs}')
    print(
        f"Total: {len(unresolved_map)} unresolved name(s) across {total_rows} row(s)"
    )
    print("(Add name_variants entries to club_master.csv to resolve)")


def run(
    db_path: Path,
    raw_dir: Path,
    club_master_csv: Path,
    skip_download: bool = False,
    force_download: bool = False,
    season_start: int = 1994,
    season_end: int | None = None,
) -> None:
    if season_end is None:
        season_end = datetime.date.today().year

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(CREATE_STANDINGS_SQL)
    conn.commit()
    _migrate_standings_columns(conn)

    entities.seed_club_master(conn, club_master_csv)
    resolver = entities.build_resolver(conn)

    if not skip_download:
        download.download_all(
            raw_dir,
            season_start=season_start,
            season_end=season_end,
            force=force_download,
        )

    csv_files = sorted(raw_dir.glob("*.csv"))
    if not csv_files:
        logger.warning("No CSV files found in %s", raw_dir)

    unresolved_map: dict[str, list[str]] = defaultdict(list)
    total_rows = 0

    for csv_path in csv_files:
        parsed = _parse_filename(csv_path.name)
        if parsed is None:
            logger.debug("Skipping unrecognised file: %s", csv_path.name)
            continue

        year, tier = parsed
        if not (season_start <= year <= season_end):
            continue

        n = _process_season(conn, csv_path, year, tier, resolver, unresolved_map)
        total_rows += n

    logger.info("Inserted/updated %d standings rows total", total_rows)

    _reconcile_statuses(conn)

    trajectory.rebuild_trajectory(conn)

    conn.close()

    _print_unresolved_report(unresolved_map)


def main() -> None:
    parser = argparse.ArgumentParser(description="English football historical database pipeline")
    parser.add_argument("--skip-download", action="store_true", help="Use cached CSVs only")
    parser.add_argument("--force-download", action="store_true", help="Re-download existing CSVs")
    parser.add_argument("--season-start", type=int, default=1994, metavar="YEAR")
    parser.add_argument("--season-end", type=int, default=None, metavar="YEAR")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=PROJECT_ROOT / "data" / "db" / "england.db",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw",
    )
    args = parser.parse_args()

    run(
        db_path=args.db_path,
        raw_dir=args.raw_dir,
        club_master_csv=PROJECT_ROOT / "club_master.csv",
        skip_download=args.skip_download,
        force_download=args.force_download,
        season_start=args.season_start,
        season_end=args.season_end,
    )


if __name__ == "__main__":
    main()
