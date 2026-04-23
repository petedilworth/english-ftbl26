"""
Manage the club_master table and provide name-resolution lookups.
"""

import json
import logging
import sqlite3
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Override specific (raw_name_lower, season_end_year) → club_id mappings
# that cannot be handled by static name_variants alone.
SEASON_OVERRIDES: dict[tuple[str, int], str] = {
    # Wimbledon FC relocated to Milton Keynes; CSV still says "Wimbledon" in 2003/04
    ("wimbledon", 2004): "mk-dons-fc",
    ("wimbledon", 2005): "mk-dons-fc",
}

CREATE_CLUB_MASTER_SQL = """
CREATE TABLE IF NOT EXISTS club_master (
    club_id           TEXT PRIMARY KEY,
    canonical_name    TEXT NOT NULL,
    name_variants     TEXT,
    lineage_parent_id TEXT,
    current_tier      INT
);
"""


def seed_club_master(conn: sqlite3.Connection, csv_path: Path) -> None:
    """
    Create club_master table (if absent) and upsert all rows from club_master.csv.
    """
    conn.execute(CREATE_CLUB_MASTER_SQL)
    conn.commit()

    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    required = {"club_id", "canonical_name", "name_variants", "lineage_parent_id", "current_tier"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"club_master.csv missing columns: {missing}")

    cursor = conn.cursor()
    for _, row in df.iterrows():
        cursor.execute(
            """
            INSERT OR REPLACE INTO club_master
                (club_id, canonical_name, name_variants, lineage_parent_id, current_tier)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                row["club_id"].strip(),
                row["canonical_name"].strip(),
                row["name_variants"].strip() or None,
                row["lineage_parent_id"].strip() or None,
                int(row["current_tier"]) if row["current_tier"].strip() else None,
            ),
        )
    conn.commit()
    logger.info("Seeded club_master with %d rows", len(df))


def build_resolver(conn: sqlite3.Connection) -> dict[str, str]:
    """
    Build a {lowercase_name_variant: club_id} lookup from the club_master table.
    Includes canonical_name and every entry in name_variants.
    Called once at pipeline startup.
    """
    resolver: dict[str, str] = {}

    cursor = conn.execute(
        "SELECT club_id, canonical_name, name_variants FROM club_master"
    )
    for club_id, canonical_name, name_variants_json in cursor.fetchall():
        _add_variant(resolver, canonical_name, club_id)

        if name_variants_json:
            try:
                variants = json.loads(name_variants_json)
                for v in variants:
                    _add_variant(resolver, v, club_id)
            except json.JSONDecodeError:
                logger.warning("Invalid name_variants JSON for %s", club_id)

    logger.info("Resolver built with %d name variants", len(resolver))
    return resolver


def _add_variant(resolver: dict[str, str], name: str, club_id: str) -> None:
    key = name.strip().lower()
    if not key:
        return
    if key in resolver and resolver[key] != club_id:
        # Collision: two clubs share the same variant — log and keep first (alphabetical)
        existing = resolver[key]
        winner = min(existing, club_id)
        logger.error(
            "Name variant collision: '%s' maps to both '%s' and '%s' — keeping '%s'",
            key,
            existing,
            club_id,
            winner,
        )
        resolver[key] = winner
    else:
        resolver[key] = club_id


def resolve_name(
    raw_name: str,
    resolver: dict[str, str],
    season_end_year: int | None = None,
) -> str | None:
    """
    Return club_id for raw_name, or None if unresolved.
    Checks SEASON_OVERRIDES first, then the general resolver.
    Pure function — no I/O.
    """
    key = raw_name.strip().lower()

    if season_end_year is not None:
        override = SEASON_OVERRIDES.get((key, season_end_year))
        if override is not None:
            return override

    return resolver.get(key)
