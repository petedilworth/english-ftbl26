import sqlite3
from collections import defaultdict
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
    unfinished = pipeline._in_progress_seasons(conn)
    for (tier, season), winner_id in status.CURRENT_SEASON_PLAYOFF_WINNERS.items():
        has_next_season = conn.execute(
            "SELECT 1 FROM standings WHERE season_end_year = ? AND tier = ? LIMIT 1",
            (season + 1, tier),
        ).fetchone()
        # A season still being played can't supersede the recorded winner, so
        # the entry still has to be valid - mirrors _apply_known_playoff_winners.
        if has_next_season and season + 1 not in unfinished:
            continue  # superseded by real movement - entry is fine to be stale
        row = conn.execute(
            "SELECT status FROM standings WHERE season_end_year=? AND tier=? AND club_id=?",
            (season, tier, winner_id),
        ).fetchone()
        assert row is not None, f"{winner_id} has no row for tier {tier} {season}"


# ── Division-identity guards ────────────────────────────────────────────────
# In August 2026 football-data.co.uk answered requests for the not-yet-published
# 2026/27 Premier League and League Two files with National League data, and
# returned HTTP 200 for both. Tier came from the requested filename, so the same
# 24-club National League table landed in the database three times, under tiers
# 1, 4 and 5 - and then rewrote the previous season's promotions.

import pandas as pd

import download


CREATE_MATCHES_SQL = """
CREATE TABLE matches (
    season_end_year INT, tier INT, match_date TEXT, home_club_id TEXT,
    away_club_id TEXT, home_name TEXT, away_name TEXT, fthg INT, ftag INT, ftr TEXT
)
"""


def _frame(div_code, n_clubs=4):
    """A minimal results frame stamped with a division code."""
    rows = []
    for i in range(0, n_clubs, 2):
        rows.append({
            "Div": div_code, "Date": "08/08/2026",
            "HomeTeam": f"Club {i}", "AwayTeam": f"Club {i + 1}",
            "FTHG": 1, "FTAG": 0, "FTR": "H",
        })
    return pd.DataFrame(rows)


def test_csv_holding_another_division_is_rejected():
    # A file named for the Premier League that actually contains National
    # League results must not be ingested as tier 1.
    assert not pipeline._division_matches_tier(
        _frame("EC"), Path("2627_E0.csv"), tier=1
    )


def test_csv_holding_the_expected_division_is_accepted():
    assert pipeline._division_matches_tier(_frame("E0"), Path("2627_E0.csv"), tier=1)


def test_csv_without_a_div_column_is_left_alone():
    # Nothing to check against, so this guard must not block the ingest.
    frame = _frame("E0").drop(columns=["Div"])
    assert pipeline._division_matches_tier(frame, Path("2627_E0.csv"), tier=1)


def test_table_with_more_clubs_than_the_division_holds_is_rejected():
    # The 24-club "Premier League" that gave the incident away.
    too_many = pd.DataFrame({"club_name": [f"Club {i}" for i in range(24)]})
    assert not pipeline._club_count_plausible(
        too_many, 2027, tier=1, csv_path=Path("2627_E0.csv")
    )


def test_table_with_fewer_clubs_is_allowed():
    # Early in a season not every club has played, so a short table is normal.
    few = pd.DataFrame({"club_name": [f"Club {i}" for i in range(6)]})
    assert pipeline._club_count_plausible(
        few, 2027, tier=1, csv_path=Path("2627_E0.csv")
    )


def test_division_code_is_read_from_the_csv_body():
    body = b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\nEC,08/08/2026,Woking,Barrow,1,0,H\n"
    assert download.division_code_in_csv(body) == "EC"


def test_division_code_is_none_without_a_div_column():
    body = b"Date,HomeTeam,AwayTeam\n08/08/2026,Woking,Barrow\n"
    assert download.division_code_in_csv(body) is None


def test_wrong_division_csv_inserts_nothing(tmp_path):
    # End-to-end version of the incident: the file is named for tier 1 but
    # holds National League data, so no rows may reach the database.
    csv_path = tmp_path / "2627_E0.csv"
    csv_path.write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "EC,08/08/2026,Woking,Barrow,1,0,H\n"
        "EC,08/08/2026,Altrincham,Southend,1,3,A\n"
    )
    conn = sqlite3.connect(":memory:")
    conn.execute(CREATE_STANDINGS_SQL)
    conn.execute(CREATE_MATCHES_SQL)

    inserted = pipeline._process_season(
        conn, csv_path, 2027, tier=1, resolver={}, unresolved_map=defaultdict(list)
    )

    assert inserted == 0
    assert conn.execute("SELECT COUNT(*) FROM standings").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0


# ── In-progress seasons ─────────────────────────────────────────────────────


def test_past_season_counts_as_complete_even_when_sparse():
    # Some early football-data.co.uk files hold only part of a season; those
    # tables are still settled history and keep their outcomes.
    assert pipeline._season_is_complete(2003, n_teams=24, n_matches=335)


def test_current_season_with_one_matchday_is_not_complete():
    live = download.current_season_end_year()
    assert not pipeline._season_is_complete(live, n_teams=24, n_matches=12)


def test_in_progress_season_gets_no_promotion_or_relegation():
    standings = pd.DataFrame({"position": [1, 2, 23, 24]})
    result = status.assign_status(standings, 2027, tier=5, is_complete=False)
    assert set(result["status"]) == {status.IN_PROGRESS}


def test_completed_season_is_not_rewritten_by_a_season_still_being_played():
    # The corruption path: National League clubs appeared in a part-played
    # season, and last season's table was rewritten to say they went up.
    conn = _db([
        (2026, 5, "woking-fc", "Stayed"),
        (2027, 5, "woking-fc", status.IN_PROGRESS),
    ])
    pipeline._reconcile_statuses(conn)
    assert conn.execute(
        "SELECT status FROM standings WHERE club_id='woking-fc' AND season_end_year=2026"
    ).fetchone()[0] == "Stayed"


def test_completed_season_is_still_reconciled_against_a_finished_one():
    # The guard above must not disable genuine movement-based correction.
    conn = _db([
        (2025, 5, "promoted-fc", "Stayed"),
        (2026, 4, "promoted-fc", "Stayed"),
    ])
    pipeline._reconcile_statuses(conn)
    assert conn.execute(
        "SELECT status FROM standings WHERE club_id='promoted-fc' AND season_end_year=2025"
    ).fetchone()[0] == "Promoted"


def _curtailed_db(rows):
    """rows: (club_id, position, points, played, gd, gf, status)."""
    conn = sqlite3.connect(":memory:")
    conn.execute(CREATE_STANDINGS_SQL)
    for club_id, position, points, played, gd, gf, stat in rows:
        conn.execute(
            "INSERT INTO standings (season_end_year, tier, club_id, club_name,"
            " position, played, gf, ga, gd, points, status)"
            " VALUES (2020, 5, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (club_id, club_id, position, played, gf, gf - gd, gd, points, stat),
        )
    conn.commit()
    return conn


def test_curtailed_division_is_reranked_on_points_per_game():
    # The 2019/20 National League in miniature. Barnet played four games
    # fewer than everyone else and finished eleventh on raw points; on the
    # rate the division was actually settled by, they were seventh - which
    # is why they were in the play-offs.
    conn = _curtailed_db([
        ("played-more-fc", 1, 58, 39, 10, 50, "Stayed"),
        ("barnet-fc", 2, 54, 35, 10, 50, "Stayed"),
    ])
    pipeline._rerank_curtailed_divisions(conn)
    order = conn.execute(
        "SELECT club_id FROM standings WHERE season_end_year = 2020 ORDER BY position"
    ).fetchall()
    assert [c for (c,) in order] == ["barnet-fc", "played-more-fc"]


def test_reranking_a_curtailed_division_leaves_the_outcomes_alone():
    # Positions are recomputed; who went up is a matter of record and stays
    # attached to the club, not to the row it now occupies.
    conn = _curtailed_db([
        ("champions-fc", 1, 70, 37, 30, 70, "Champions"),
        ("slower-fc", 2, 71, 40, 30, 70, "Stayed"),
    ])
    pipeline._rerank_curtailed_divisions(conn)
    rows = dict(conn.execute(
        "SELECT club_id, status FROM standings WHERE season_end_year = 2020"
    ).fetchall())
    assert rows["champions-fc"] == "Champions"
    assert conn.execute(
        "SELECT position FROM standings WHERE club_id = 'champions-fc'"
    ).fetchone()[0] == 1


def test_a_full_curtailed_division_is_left_untouched():
    # Every club played the same number of games, so the rate ordering and
    # the points ordering are the same table.
    conn = _curtailed_db([
        ("first-fc", 1, 70, 40, 30, 70, "Champions"),
        ("second-fc", 2, 60, 40, 20, 60, "Stayed"),
    ])
    pipeline._rerank_curtailed_divisions(conn)
    assert conn.execute(
        "SELECT position FROM standings WHERE club_id = 'second-fc'"
    ).fetchone()[0] == 2
