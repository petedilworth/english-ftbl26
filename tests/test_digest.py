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


# ── Natural level ──────────────────────────────────────────────────────

def _level_db():
    """A club with a Bolton-shaped record: top flight, then a slide."""
    conn = _make_db()
    conn.execute("INSERT INTO club_master VALUES ('slider-fc','Slider FC',NULL,NULL,3)")
    for year in range(2000, 2026):
        tier = 1 if year < 2012 else 2 if year < 2021 else 3
        conn.execute(
            "INSERT INTO standings (season_end_year, tier, division_name, club_id,"
            " club_name, position, played, won, drawn, lost, gf, ga, gd, points,"
            " status, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (year, tier, "Div", "slider-fc", "Slider FC", 10,
             46, 18, 10, 18, 55, 55, 0, 64, "Stayed", "test"),
        )
    trajectory.rebuild_trajectory(conn)
    return conn


def test_level_sentence_replaces_the_fallen_giant_wording():
    conn = _level_db()
    ctx = digest.club_context(conn, "slider-fc")
    sentence = digest._history_sentence(ctx)
    assert "fallen giant" not in sentence.lower()
    # Describes the club, then how far it currently sits from that
    assert "Slider FC" in sentence
    assert "below that now" in sentence


def test_storyline_score_rewards_distance_from_the_natural_level():
    conn = _level_db()
    off_level = digest.club_context(conn, "slider-fc")
    at_level = dict(off_level, natural_level_gap=0)
    fixture = {"tier": 3, "division_name": "League One"}
    high = digest.storyline_score(fixture, off_level, None, set())
    low = digest.storyline_score(fixture, at_level, None, set())
    assert high > low


def test_digest_survives_a_database_without_natural_level_columns():
    # The database file is committed, so a checkout can carry a
    # club_trajectory predating this feature. It must degrade, not raise.
    conn = _make_db()
    conn.execute("DROP TABLE IF EXISTS club_trajectory")
    conn.execute(
        "CREATE TABLE club_trajectory (club_id TEXT PRIMARY KEY, canonical_name TEXT,"
        " current_tier INT, current_tier_streak INT, highest_tier INT, lowest_tier INT,"
        " seasons_in_tier1 INT, last_tier1_season INT, first_season_in_db INT,"
        " last_season_in_db INT, total_promotions INT, total_relegations INT,"
        " yo_yo_score REAL)"
    )
    conn.execute(
        "INSERT INTO club_trajectory VALUES ('giant-fc','Giant FC',3,2,1,3,5,2015,"
        "2010,2025,2,3,0.4)"
    )
    ctx = digest.club_context(conn, "giant-fc")
    assert ctx is not None
    assert ctx["natural_level_tier"] is None      # back-filled, not missing
    # Falls back to the old fallen-giant wording rather than blowing up
    assert "fallen giant" in digest._history_sentence(ctx).lower()
