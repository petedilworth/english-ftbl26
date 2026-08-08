import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pipeline
import status

CREATE_STANDINGS_SQL = """
CREATE TABLE standings (
    season_end_year INT, tier INT, division_name TEXT, club_id TEXT,
    club_name TEXT, position INT, played INT, won INT, drawn INT,
    lost INT, gf INT, ga INT, gd INT, points INT, status TEXT, source TEXT
)
"""


def _db(rows):
    """rows: list of (season_end_year, tier, club_id, status)."""
    conn = sqlite3.connect(":memory:")
    conn.execute(CREATE_STANDINGS_SQL)
    for season, tier, club_id, stat in rows:
        conn.execute(
            "INSERT INTO standings (season_end_year, tier, club_id, club_name, status)"
            " VALUES (?, ?, ?, ?, ?)",
            (season, tier, club_id, club_id, stat),
        )
    conn.commit()
    return conn


def test_only_the_known_winner_keeps_playoff_promoted(monkeypatch):
    # Four clubs made the play-offs (the standard eligibility band), but
    # only one actually won the final - the bug this whole fix exists for.
    monkeypatch.setattr(
        status, "CURRENT_SEASON_PLAYOFF_WINNERS", {(3, 2099): "winner-fc"}
    )
    conn = _db([
        (2099, 3, "winner-fc", "Play-off Promoted"),
        (2099, 3, "loser-a-fc", "Play-off Promoted"),
        (2099, 3, "loser-b-fc", "Play-off Promoted"),
        (2099, 3, "loser-c-fc", "Play-off Promoted"),
    ])
    pipeline._apply_known_playoff_winners(conn)

    rows = dict(conn.execute("SELECT club_id, status FROM standings"))
    assert rows["winner-fc"] == "Play-off Promoted"
    assert rows["loser-a-fc"] == "Stayed"
    assert rows["loser-b-fc"] == "Stayed"
    assert rows["loser-c-fc"] == "Stayed"


def test_skipped_once_next_season_has_real_data(monkeypatch):
    # If next season is already in the database, movement-based
    # _reconcile_statuses() is more direct evidence than this curated
    # table - the known-winners pass must not fight it or reapply.
    monkeypatch.setattr(
        status, "CURRENT_SEASON_PLAYOFF_WINNERS", {(3, 2099): "winner-fc"}
    )
    conn = _db([
        (2099, 3, "winner-fc", "Play-off Promoted"),
        (2099, 3, "loser-a-fc", "Play-off Promoted"),  # would be "corrected"...
        (2100, 3, "loser-a-fc", "Champions"),           # ...but really did move up
    ])
    pipeline._apply_known_playoff_winners(conn)

    status_val = conn.execute(
        "SELECT status FROM standings WHERE club_id='loser-a-fc' AND season_end_year=2099"
    ).fetchone()[0]
    assert status_val == "Play-off Promoted"  # untouched, left for reconcile_statuses


def test_no_matching_rows_is_a_silent_no_op(monkeypatch):
    monkeypatch.setattr(
        status, "CURRENT_SEASON_PLAYOFF_WINNERS", {(3, 2099): "winner-fc"}
    )
    conn = _db([(2099, 3, "someone-else-fc", "Stayed")])
    pipeline._apply_known_playoff_winners(conn)  # must not raise
    status_val = conn.execute(
        "SELECT status FROM standings WHERE club_id='someone-else-fc'"
    ).fetchone()[0]
    assert status_val == "Stayed"


def test_real_table_entries_reference_playoff_promoted_rows_in_the_live_db():
    # Guards against a stale club_id (e.g. a typo, or a club_id that later
    # changed) silently making CURRENT_SEASON_PLAYOFF_WINNERS a no-op.
    db_path = Path(__file__).parent.parent / "data" / "db" / "england.db"
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    for (tier, season), winner_id in status.CURRENT_SEASON_PLAYOFF_WINNERS.items():
        has_next_season = conn.execute(
            "SELECT 1 FROM standings WHERE season_end_year = ? AND tier = ? LIMIT 1",
            (season + 1, tier),
        ).fetchone()
        if has_next_season:
            continue  # superseded by real movement - entry is fine to be stale
        row = conn.execute(
            "SELECT status FROM standings WHERE season_end_year=? AND tier=? AND club_id=?",
            (season, tier, winner_id),
        ).fetchone()
        assert row is not None, f"{winner_id} has no row for tier {tier} {season}"
