"""
Build the club_trajectory table from the standings table.
This table is fully derived and is dropped and rebuilt on every pipeline run.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)

CREATE_TRAJECTORY_SQL = """
CREATE TABLE club_trajectory (
    club_id             TEXT PRIMARY KEY,
    canonical_name      TEXT,
    current_tier        INT,
    current_tier_streak INT,
    highest_tier        INT,
    lowest_tier         INT,
    seasons_in_tier1    INT,
    last_tier1_season   INT,
    first_season_in_db  INT,
    last_season_in_db   INT,
    total_promotions    INT,
    total_relegations   INT,
    yo_yo_score         REAL
);
"""

AGGREGATE_SQL = """
SELECT
    s.club_id,
    cm.canonical_name,
    cm.current_tier,
    MIN(s.tier)                                                         AS highest_tier,
    MAX(s.tier)                                                         AS lowest_tier,
    SUM(CASE WHEN s.tier = 1 THEN 1 ELSE 0 END)                        AS seasons_in_tier1,
    MAX(CASE WHEN s.tier = 1 THEN s.season_end_year ELSE NULL END)      AS last_tier1_season,
    MIN(s.season_end_year)                                              AS first_season_in_db,
    MAX(s.season_end_year)                                              AS last_season_in_db,
    COUNT(DISTINCT s.season_end_year)                                   AS seasons_in_db,
    SUM(CASE WHEN s.status IN ('Champions','Promoted','Play-off Promoted')
             THEN 1 ELSE 0 END)                                        AS total_promotions,
    SUM(CASE WHEN s.status IN ('Relegated','Play-off Relegated')
             THEN 1 ELSE 0 END)                                        AS total_relegations
FROM standings s
JOIN club_master cm ON cm.club_id = s.club_id
WHERE s.club_id IS NOT NULL
GROUP BY s.club_id
"""


def _compute_tier_streaks(conn: sqlite3.Connection) -> dict[str, int]:
    """
    For each club, count consecutive seasons at their current tier counting
    backwards from their most recent season in the DB. A gap in seasons
    (club absent from Tiers 1-5) breaks the streak.
    Returns {club_id: streak}.
    """
    rows = conn.execute(
        """
        SELECT s.club_id, s.season_end_year, s.tier, cm.current_tier
        FROM standings s
        JOIN club_master cm ON cm.club_id = s.club_id
        WHERE s.club_id IS NOT NULL
        ORDER BY s.club_id, s.season_end_year DESC
        """
    ).fetchall()

    streaks: dict[str, int] = {}
    done: set[str] = set()
    current_club = None
    prev_season = None

    for club_id, season, tier, current_tier in rows:
        if club_id != current_club:
            current_club = club_id
            prev_season = None
            streaks[club_id] = 0
            # Stale club_master detection: most recent tier should match
            if tier != current_tier:
                logger.warning(
                    "club_master.current_tier=%s for %s but most recent "
                    "standings tier is %s — streak will be 0; "
                    "update club_master.csv",
                    current_tier, club_id, tier,
                )

        if club_id in done:
            continue

        gap = prev_season is not None and prev_season - season > 1
        if tier == current_tier and not gap:
            streaks[club_id] += 1
            prev_season = season
        else:
            done.add(club_id)

    return streaks


def rebuild_trajectory(conn: sqlite3.Connection) -> None:
    """
    Drop and recreate club_trajectory from standings + club_master.
    """
    conn.execute("DROP TABLE IF EXISTS club_trajectory")
    conn.execute(CREATE_TRAJECTORY_SQL)

    rows = conn.execute(AGGREGATE_SQL).fetchall()
    columns = [
        "club_id", "canonical_name", "current_tier",
        "highest_tier", "lowest_tier",
        "seasons_in_tier1", "last_tier1_season",
        "first_season_in_db", "last_season_in_db",
        "seasons_in_db",
        "total_promotions", "total_relegations",
    ]

    streaks = _compute_tier_streaks(conn)

    insert_rows = []
    for row in rows:
        d = dict(zip(columns, row))
        seasons = d["seasons_in_db"] or 1
        promo = d["total_promotions"] or 0
        relg = d["total_relegations"] or 0
        yo_yo = round((promo + relg) / seasons, 2)

        insert_rows.append((
            d["club_id"],
            d["canonical_name"],
            d["current_tier"],
            streaks.get(d["club_id"], 0),
            d["highest_tier"],
            d["lowest_tier"],
            d["seasons_in_tier1"],
            d["last_tier1_season"],
            d["first_season_in_db"],
            d["last_season_in_db"],
            promo,
            relg,
            yo_yo,
        ))

    conn.executemany(
        """
        INSERT INTO club_trajectory (
            club_id, canonical_name, current_tier, current_tier_streak,
            highest_tier, lowest_tier, seasons_in_tier1, last_tier1_season,
            first_season_in_db, last_season_in_db,
            total_promotions, total_relegations, yo_yo_score
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        insert_rows,
    )
    conn.commit()
    logger.info("Rebuilt club_trajectory with %d rows", len(insert_rows))
