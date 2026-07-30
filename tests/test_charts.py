import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from charts import fixture_chart, overall_positions, tier_floors


def _standings_db(rows):
    """rows: list of (club_id, season, tier, position, status)"""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE standings (season_end_year INT, tier INT, club_id TEXT,"
        " position INT, status TEXT)"
    )
    for club_id, season, tier, position, status in rows:
        conn.execute(
            "INSERT INTO standings VALUES (?,?,?,?,?)",
            (season, tier, club_id, position, status),
        )
    return conn


def test_tier_floors_cumulative_boundaries():
    rows = [
        ("a", 2023, 1, 1, "Champions"), ("b", 2023, 1, 2, "Stayed"),
        ("c", 2023, 2, 1, "Champions"), ("d", 2023, 2, 2, "Stayed"), ("e", 2023, 2, 3, "Stayed"),
        ("a", 2024, 1, 1, "Champions"), ("b", 2024, 1, 2, "Stayed"),
        ("c", 2024, 2, 1, "Champions"), ("d", 2024, 2, 2, "Stayed"), ("e", 2024, 2, 3, "Stayed"),
        ("f", 2024, 3, 1, "Champions"), ("g", 2024, 3, 2, "Stayed"),
    ]
    conn = _standings_db(rows)
    floors_by_year, max_pos = tier_floors(conn)
    assert floors_by_year[2023] == [2]       # one boundary: 2 clubs in tier 1
    assert floors_by_year[2024] == [2, 5]    # boundaries after tier 1 (2) and tier 2 (2+3)
    assert max_pos == 7                      # 2024 has 2+3+2 = 7 total


def test_overall_position_offset_by_higher_tiers():
    rows = [
        ("a", 2024, 1, 1, "Champions"), ("b", 2024, 1, 2, "Stayed"),
        ("target", 2024, 2, 3, "Stayed"),
    ]
    conn = _standings_db(rows)
    points = overall_positions(conn, "target")
    assert points == [(2024, 5, None)]  # position 3 in tier 2 + 2 clubs above


def test_tier1_champions_is_not_a_promotion_event():
    # The exact Man City bug class: winning the Premier League is a title,
    # not a promotion, because there's no tier above it.
    conn = _standings_db([("dynasty", 2024, 1, 1, "Champions")])
    points = overall_positions(conn, "dynasty")
    assert points == [(2024, 1, None)]


def test_lower_tier_title_is_a_promotion_event():
    conn = _standings_db([("riser", 2024, 2, 1, "Champions")])
    points = overall_positions(conn, "riser")
    assert points[0][2] == "promoted"


def test_playoff_promotion_counts_but_not_at_tier1():
    conn = _standings_db([
        ("a", 2024, 4, 5, "Play-off Promoted"),
        ("b", 2024, 1, 1, "Champions"),
    ])
    assert overall_positions(conn, "a")[0][2] == "promoted"
    assert overall_positions(conn, "b")[0][2] is None


def test_relegation_is_an_event_at_any_tier():
    conn = _standings_db([
        ("bottom5", 2024, 5, 22, "Relegated"),
        ("playoff-down", 2024, 2, 22, "Play-off Relegated"),
    ])
    assert overall_positions(conn, "bottom5")[0][2] == "relegated"
    assert overall_positions(conn, "playoff-down")[0][2] == "relegated"


def test_stayed_has_no_event():
    conn = _standings_db([("mid-table", 2024, 3, 12, "Stayed")])
    assert overall_positions(conn, "mid-table")[0][2] is None


def test_fixture_chart_default_has_no_tier_lines_or_events(tmp_path):
    # Digest email call site: defaults must stay visually unchanged.
    conn = _standings_db([
        ("home", 2023, 2, 1, "Champions"), ("home", 2024, 1, 10, "Stayed"),
        ("away", 2023, 3, 1, "Champions"), ("away", 2024, 2, 15, "Stayed"),
    ])
    out = fixture_chart(conn, "home", "away", "Home FC", "Away FC", tmp_path / "chart.png")
    assert out is not None and out.exists() and out.stat().st_size > 0


def test_fixture_chart_with_tier_lines_and_events(tmp_path):
    conn = _standings_db([
        ("home", 2023, 2, 1, "Champions"), ("home", 2024, 1, 10, "Stayed"),
    ])
    out = fixture_chart(
        conn, "home", None, "Home FC", "", tmp_path / "chart.png",
        show_tier_lines=True, show_events=True,
    )
    assert out is not None and out.exists() and out.stat().st_size > 0


def test_fixture_chart_none_when_no_history(tmp_path):
    conn = _standings_db([])
    assert fixture_chart(conn, None, None, "A", "B", tmp_path / "chart.png") is None
