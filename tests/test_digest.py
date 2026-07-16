import datetime
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import digest
import trajectory


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE club_master (club_id TEXT PRIMARY KEY, canonical_name TEXT,"
        " name_variants TEXT, lineage_parent_id TEXT, current_tier INT)"
    )
    conn.execute(
        "CREATE TABLE standings (season_end_year INT, tier INT, division_name TEXT,"
        " club_id TEXT, club_name TEXT, position INT, played INT, won INT, drawn INT,"
        " lost INT, gf INT, ga INT, gd INT, points INT, status TEXT, source TEXT)"
    )
    conn.execute(
        "CREATE TABLE matches (season_end_year INT, tier INT, match_date TEXT,"
        " home_club_id TEXT, away_club_id TEXT, home_name TEXT, away_name TEXT,"
        " fthg INT, ftag INT, ftr TEXT)"
    )

    # Giant FC: ex-tier-1 club now in tier 3. Steady FC: career tier-3 club.
    clubs = [("giant-fc", "Giant FC"), ("steady-fc", "Steady FC")]
    for cid, name in clubs:
        conn.execute("INSERT INTO club_master VALUES (?,?,NULL,NULL,3)", (cid, name))

    history = {
        "giant-fc": [(2022, 1, 20, "Relegated"), (2023, 2, 23, "Relegated"),
                     (2024, 3, 10, "Stayed"), (2025, 3, 8, "Stayed")],
        "steady-fc": [(2022, 3, 12, "Stayed"), (2023, 3, 11, "Stayed"),
                      (2024, 3, 9, "Stayed"), (2025, 3, 7, "Stayed")],
    }
    for cid, rows in history.items():
        name = dict(clubs)[cid]
        for year, tier, pos, st in rows:
            conn.execute(
                "INSERT INTO standings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (year, tier, "League One", cid, name, pos,
                 46, 15, 10, 21, 50, 60, -10, 55, st, "test"),
            )

    conn.execute(
        "INSERT INTO matches VALUES (2025, 3, '2025-03-01',"
        " 'giant-fc', 'steady-fc', 'Giant FC', 'Steady FC', 2, 1, 'H')"
    )
    conn.execute(
        "INSERT INTO matches VALUES (2025, 3, '2025-04-01',"
        " 'steady-fc', 'giant-fc', 'Steady FC', 'Giant FC', 0, 0, 'D')"
    )
    trajectory.rebuild_trajectory(conn)
    return conn


def _fixture():
    return {
        "div": "E2", "tier": 3, "division_name": "League One",
        "date": datetime.date(2026, 8, 15), "time": "15:00",
        "home_name": "Giant FC", "away_name": "Steady FC",
        "home_id": "giant-fc", "away_id": "steady-fc",
    }


def test_club_context_and_head_to_head():
    conn = _make_db()
    ctx = digest.club_context(conn, "giant-fc")
    assert ctx["name"] == "Giant FC"
    assert ctx["highest_tier"] == 1
    assert ctx["position"] == 8

    h2h = digest.head_to_head(conn, "giant-fc", "steady-fc")
    assert h2h == {"total": 2, "a_wins": 1, "b_wins": 0, "draws": 1}


def test_fallen_giant_scores_higher_than_plain_fixture():
    conn = _make_db()
    f = _fixture()
    home = digest.club_context(conn, "giant-fc")
    away = digest.club_context(conn, "steady-fc")
    with_giant = digest.storyline_score(f, home, away, set())
    without = digest.storyline_score(f, away, away, set())
    assert with_giant > without


def test_followed_club_dominates_scoring():
    conn = _make_db()
    f = _fixture()
    home = digest.club_context(conn, "giant-fc")
    away = digest.club_context(conn, "steady-fc")
    assert digest.storyline_score(f, home, away, {"steady-fc"}) >= 100


def test_build_digest_renders(tmp_path):
    conn = _make_db()
    subject, html, text, images = digest.build_digest(conn, [_fixture()], tmp_path)
    assert "Giant FC" in html and "Steady FC" in html
    assert "Giant FC" in text
    assert "fallen giant" in html  # narrative engaged for ex-tier-1 club
    assert "1 fixtures" in subject
    assert len(images) == 1 and images[0][0].exists()  # chart rendered
