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
import finances
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

CREATE_MATCHES_SQL = """
CREATE TABLE IF NOT EXISTS matches (
    season_end_year INT  NOT NULL,
    tier            INT  NOT NULL,
    match_date      TEXT,
    home_club_id    TEXT,
    away_club_id    TEXT,
    home_name       TEXT NOT NULL,
    away_name       TEXT NOT NULL,
    fthg            INT,
    ftag            INT,
    ftr             TEXT
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


def _division_matches_tier(match_df, csv_path: Path, tier: int) -> bool:
    """
    Check a loaded CSV really holds the division its filename claims.

    The tier is derived from the filename, which only records what we asked
    the site for. Every football-data.co.uk row carries its own 'Div' code,
    and that is what actually determines the division — in August 2026 the
    site answered requests for not-yet-published Premier League and League
    Two files with National League data, which was then stored under three
    different tiers.
    """
    if "Div" not in match_df.columns:
        logger.debug("%s has no Div column — cannot verify division", csv_path.name)
        return True

    codes = {str(c).strip() for c in match_df["Div"].dropna().unique() if str(c).strip()}
    if not codes:
        return True

    expected = download.TIER_TO_CODE[tier]
    unexpected = codes - {expected}
    if unexpected:
        logger.error(
            "%s claims tier %d (%s) but contains %s data — skipping file",
            csv_path.name,
            tier,
            expected,
            "/".join(sorted(unexpected)),
        )
        return False
    return True


def _season_is_complete(season_end_year: int, n_teams: int, n_matches: int) -> bool:
    """
    Whether a season has finished and its final table can be judged.

    Past seasons count as finished however sparse their data — some early
    football-data.co.uk files hold only part of a season, and those tables
    are still settled history. Only the season currently being played is
    tested on how many of its fixtures have actually happened.
    """
    if season_end_year < download.current_season_end_year():
        return True
    return n_matches >= aggregate.expected_match_count(n_teams) * 0.95


def _club_count_plausible(standings_df, season_end_year: int, tier: int, csv_path: Path) -> bool:
    """
    Reject a table holding more clubs than the division can contain.

    Fewer clubs than expected is normal early in a season, when some have not
    played yet, so only an excess is treated as proof the file is wrong.
    """
    try:
        expected = status.get_rules(tier, season_end_year)["total_clubs"]
    except KeyError:
        return True

    actual = len(standings_df)
    if actual > expected:
        logger.error(
            "%s produced %d clubs for tier %d %d, which holds %d — skipping file",
            csv_path.name,
            actual,
            tier,
            season_end_year,
            expected,
        )
        return False
    return True


def _process_season(
    conn: sqlite3.Connection,
    csv_path: Path,
    season_end_year: int,
    tier: int,
    resolver: dict,
    unresolved_map: dict,
) -> int:
    """
    Aggregate one season CSV, assign status, resolve names, insert into
    standings and matches. Returns count of standings rows inserted.
    """
    match_df = aggregate.load_csv(csv_path)
    if match_df is None:
        return 0

    if not _division_matches_tier(match_df, csv_path, tier):
        return 0

    try:
        standings_df = aggregate.compute_standings(match_df, season_end_year, tier)
    except Exception as exc:
        logger.error("Failed aggregating %s: %s", csv_path.name, exc)
        return 0

    if not _club_count_plausible(standings_df, season_end_year, tier, csv_path):
        return 0

    is_complete = _season_is_complete(season_end_year, len(standings_df), len(match_df))
    if not is_complete:
        logger.info(
            "%d/%d is still being played (%d matches) — no promotion or "
            "relegation outcomes assigned yet",
            season_end_year,
            tier,
            len(match_df),
        )
    standings_df = status.assign_status(
        standings_df, season_end_year, tier, is_complete=is_complete
    )
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

    match_rows = []
    for _, m in aggregate.extract_matches(match_df, season_end_year, tier).iterrows():
        match_rows.append((
            season_end_year,
            tier,
            m["match_date"],
            entities.resolve_name(m["HomeTeam"], resolver, season_end_year),
            entities.resolve_name(m["AwayTeam"], resolver, season_end_year),
            m["HomeTeam"],
            m["AwayTeam"],
            int(m["FTHG"]),
            int(m["FTAG"]),
            m["FTR"],
        ))

    try:
        # Replace the season wholesale rather than upserting: a club dropping
        # out of a re-parsed table would otherwise leave a stale row behind.
        conn.execute(
            "DELETE FROM standings WHERE season_end_year = ? AND tier = ?",
            (season_end_year, tier),
        )
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
        # matches has no natural unique key across replays of the same
        # season (dates can be reparsed), so replace the season wholesale
        conn.execute(
            "DELETE FROM matches WHERE season_end_year = ? AND tier = ?",
            (season_end_year, tier),
        )
        conn.executemany(
            """
            INSERT INTO matches
                (season_end_year, tier, match_date, home_club_id, away_club_id,
                 home_name, away_name, fthg, ftag, ftr)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            match_rows,
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("Failed inserting %d/%d: %s", season_end_year, tier, exc)
        return 0

    return len(rows)


def _in_progress_seasons(conn: sqlite3.Connection) -> set[int]:
    """
    Seasons still being played, which prove nothing about promotion yet.

    A part-played table is not evidence of where anyone finished, and must
    never be used to rewrite a completed season's outcomes.
    """
    return {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT season_end_year FROM standings WHERE status = ?",
            (status.IN_PROGRESS,),
        )
    }


def _reconcile_statuses(conn: sqlite3.Connection) -> None:
    """
    Correct positional status assignments using observed movement.

    Play-off positions mark eligibility, but only the winner goes up; a club's
    actual tier next season is ground truth. Rows for the latest season, and
    clubs with no row the following season (folded or dropped below Tier 5),
    keep their positional status here - see _apply_known_playoff_winners()
    for how the latest season's play-off rows get corrected instead.

    A season that is still being played is ignored as evidence: it says where
    clubs are now, not where they finished, and treating it as ground truth
    let one bad ingest rewrite the previous season's promotions wholesale.
    """
    unfinished = _in_progress_seasons(conn)

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
        if season + 1 in unfinished or status_val == status.IN_PROGRESS:
            continue
        moved_up = next_tier < tier
        moved_down = next_tier > tier

        # Per-row corrections are logged at DEBUG: they recur on every full
        # rebuild (positional statuses are re-derived, then re-corrected)
        # and are expected — play-off losers, reprieves, expulsions.
        if status_val == "Play-off Promoted" and not moved_up:
            updates.append(("Stayed", rowid))
        elif status_val == "Promoted" and not moved_up:
            logger.debug(
                "%s marked Promoted in %d (tier %d) but did not move up — "
                "setting Stayed", club_id, season, tier)
            updates.append(("Stayed", rowid))
        elif status_val in ("Relegated", "Play-off Relegated") and not moved_down:
            logger.debug(
                "%s marked %s in %d (tier %d) but did not move down — "
                "setting Stayed (reprieve)", club_id, status_val, season, tier)
            updates.append(("Stayed", rowid))
        elif status_val == "Stayed" and moved_up:
            logger.debug(
                "%s marked Stayed in %d (tier %d) but moved up — "
                "setting Promoted", club_id, season, tier)
            updates.append(("Promoted", rowid))
        elif status_val == "Stayed" and moved_down:
            logger.debug(
                "%s marked Stayed in %d (tier %d) but moved down — "
                "setting Relegated", club_id, season, tier)
            updates.append(("Relegated", rowid))

    if updates:
        conn.executemany("UPDATE standings SET status = ? WHERE rowid = ?", updates)
        conn.commit()
    logger.info(
        "Status reconciliation: %d rows corrected against next-season movement",
        len(updates),
    )


def _apply_known_playoff_winners(conn: sqlite3.Connection) -> None:
    """
    Correct "Play-off Promoted" rows that _reconcile_statuses() can't reach.

    That function needs next season's data to know who actually went up;
    for the most recently completed season, next season hasn't been played
    yet, so every club in the play-off band is left tagged "Play-off
    Promoted" instead of just the winner. status.CURRENT_SEASON_PLAYOFF_
    WINNERS records the real winner for exactly that gap. If next season's
    data has since been ingested, movement-based reconciliation is more
    direct evidence than this table and takes precedence - skip it here.
    """
    unfinished = _in_progress_seasons(conn)

    updates: list[tuple[str, int]] = []
    for (tier, season), winner_id in status.CURRENT_SEASON_PLAYOFF_WINNERS.items():
        has_next_season = conn.execute(
            "SELECT 1 FROM standings WHERE season_end_year = ? AND tier = ? LIMIT 1",
            (season + 1, tier),
        ).fetchone()
        # A season underway can't settle last season's play-offs either, so
        # the recorded winner is still the better evidence.
        if has_next_season and season + 1 not in unfinished:
            continue

        rows = conn.execute(
            """
            SELECT rowid, club_id FROM standings
            WHERE season_end_year = ? AND tier = ? AND status = 'Play-off Promoted'
            """,
            (season, tier),
        ).fetchall()
        found_winner = any(club_id == winner_id for _rowid, club_id in rows)
        if not found_winner:
            logger.warning(
                "Known play-off winner %s not found among tier %d %d play-off "
                "rows - check the club_id in CURRENT_SEASON_PLAYOFF_WINNERS",
                winner_id, tier, season,
            )
        for rowid, club_id in rows:
            if club_id != winner_id:
                updates.append(("Stayed", rowid))

    if updates:
        conn.executemany("UPDATE standings SET status = ? WHERE rowid = ?", updates)
        conn.commit()
    logger.info(
        "Known play-off winners applied: %d row(s) corrected", len(updates)
    )


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
    conn.execute(CREATE_MATCHES_SQL)
    conn.commit()
    _migrate_standings_columns(conn)

    entities.seed_club_master(conn, club_master_csv)
    # After club_master, since finances rows are validated against it.
    finances.seed_club_finances(conn, PROJECT_ROOT / "club_finances.csv")
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
    _apply_known_playoff_winners(conn)

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
