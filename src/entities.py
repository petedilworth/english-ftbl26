"""
Manage the club_master table and provide name-resolution lookups.
"""

import json
import logging
import re
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_APOSTROPHES = "'‘’ʼ´`"
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

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
    Rows in the table that are no longer in the CSV are removed, so the CSV is
    the single source of truth (stale hand-added entries otherwise persist and
    cause name-variant collisions).
    """
    conn.execute(CREATE_CLUB_MASTER_SQL)
    conn.commit()

    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    required = {"club_id", "canonical_name", "name_variants", "lineage_parent_id", "current_tier"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"club_master.csv missing columns: {missing}")

    csv_ids = {cid.strip() for cid in df["club_id"]}
    db_ids = {row[0] for row in conn.execute("SELECT club_id FROM club_master")}
    stale = sorted(db_ids - csv_ids)
    if stale:
        logger.warning(
            "Removing %d club_master row(s) no longer in club_master.csv: %s",
            len(stale), ", ".join(stale),
        )
        placeholders = ",".join("?" * len(stale))
        has_standings = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='standings'"
        ).fetchone()
        if has_standings:
            # Detach references first (FK constraint); rows re-resolve on this run
            conn.execute(
                f"UPDATE standings SET club_id = NULL WHERE club_id IN ({placeholders})",
                stale,
            )
        conn.execute(
            f"DELETE FROM club_master WHERE club_id IN ({placeholders})", stale
        )
        conn.commit()

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


def _normalize(name: str) -> str:
    """
    Reduce a club name to a bare lookup key: just its letters and digits.

    Source CSVs vary in ways that shouldn't affect matching — accents,
    apostrophes, punctuation, spacing, and even invisible characters
    (zero-width spaces, byte-order marks) glued into a name. Rather than
    enumerate those, we fold accents to plain letters, drop apostrophes so
    "King's" == "Kings", and remove everything that isn't a-z0-9. What
    remains is stable regardless of cosmetic differences. Verified to
    produce no collisions across the current club_master.csv.
    """
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c)).lower()
    for apostrophe in _APOSTROPHES:
        name = name.replace(apostrophe, "")
    return _NON_ALNUM.sub("", name)


def _add_variant(resolver: dict[str, str], name: str, club_id: str) -> None:
    key = _normalize(name)
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
    key = _normalize(raw_name)

    if season_end_year is not None:
        override = SEASON_OVERRIDES.get((key, season_end_year))
        if override is not None:
            return override

    return resolver.get(key)
