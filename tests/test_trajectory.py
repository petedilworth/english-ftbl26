import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trajectory import _compute_tier_streaks, rebuild_trajectory


def _standings_db(rows):
    """rows: list of (club_id, canonical_name, current_tier, season, tier, status)"""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE club_master (club_id TEXT PRIMARY KEY, canonical_name TEXT,"
        " name_variants TEXT, lineage_parent_id TEXT, current_tier INT)"
    )
    conn.execute(
        "CREATE TABLE standings (season_end_year INT, tier INT, club_id TEXT, status TEXT)"
    )
    seen = set()
    for club_id, name, current_tier, season, tier, status in rows:
        if club_id not in seen:
            conn.execute(
                "INSERT INTO club_master VALUES (?,?,NULL,NULL,?)",
                (club_id, name, current_tier),
            )
            seen.add(club_id)
        conn.execute(
            "INSERT INTO standings VALUES (?,?,?,?)", (season, tier, club_id, status)
        )
    return conn


def test_tier1_titles_are_not_counted_as_promotions():
    # Three Premier League titles, never actually promoted (always tier 1) —
    # this is the Man City bug: winning the top flight isn't a promotion.
    rows = [
        ("dynasty-fc", "Dynasty FC", 1, 2022, 1, "Champions"),
        ("dynasty-fc", "Dynasty FC", 1, 2023, 1, "Stayed"),
        ("dynasty-fc", "Dynasty FC", 1, 2024, 1, "Champions"),
        ("dynasty-fc", "Dynasty FC", 1, 2025, 1, "Champions"),
    ]
    conn = _standings_db(rows)
    rebuild_trajectory(conn)
    total_promotions, yo_yo = conn.execute(
        "SELECT total_promotions, yo_yo_score FROM club_trajectory"
        " WHERE club_id = 'dynasty-fc'"
    ).fetchone()
    assert total_promotions == 0
    assert yo_yo == 0.0


def test_lower_tier_title_still_counts_as_promotion():
    # Winning the Championship (tier 2) genuinely promotes the club to tier 1
    rows = [
        ("riser-fc", "Riser FC", 1, 2022, 2, "Champions"),
        ("riser-fc", "Riser FC", 1, 2023, 1, "Stayed"),
    ]
    conn = _standings_db(rows)
    rebuild_trajectory(conn)
    total_promotions = conn.execute(
        "SELECT total_promotions FROM club_trajectory WHERE club_id = 'riser-fc'"
    ).fetchone()[0]
    assert total_promotions == 1


def _make_db(clubs):
    """clubs: list of (club_id, current_tier, [(season, tier), ...])"""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE club_master (club_id TEXT PRIMARY KEY, canonical_name TEXT,"
        " name_variants TEXT, lineage_parent_id TEXT, current_tier INT)"
    )
    conn.execute(
        "CREATE TABLE standings (season_end_year INT, tier INT, club_id TEXT)"
    )
    for club_id, current_tier, history in clubs:
        conn.execute(
            "INSERT INTO club_master VALUES (?,?,NULL,NULL,?)",
            (club_id, club_id, current_tier),
        )
        for season, tier in history:
            conn.execute(
                "INSERT INTO standings VALUES (?,?,?)", (season, tier, club_id)
            )
    return conn


def test_streak_simple():
    conn = _make_db([("a-fc", 1, [(2023, 1), (2024, 1)])])
    assert _compute_tier_streaks(conn)["a-fc"] == 2


def test_streak_stops_at_break_and_does_not_resume():
    # History DESC: 2,2,1,2,2,2 — older tier-2 run is LONGER than current one.
    # The pre-fix bug resumed counting after the break and returned 3.
    history = [(2019, 2), (2020, 2), (2021, 2), (2022, 1), (2023, 2), (2024, 2)]
    conn = _make_db([("yo-yo-fc", 2, history), ("zzz-fc", 1, [(2024, 1)])])
    streaks = _compute_tier_streaks(conn)
    assert streaks["yo-yo-fc"] == 2
    assert streaks["zzz-fc"] == 1


def test_streak_broken_by_season_gap():
    # Club absent from Tiers 1-5 in 2022 (e.g. dropped to Tier 6 and returned)
    history = [(2020, 5), (2021, 5), (2023, 5), (2024, 5)]
    conn = _make_db([("gap-fc", 5, history)])
    assert _compute_tier_streaks(conn)["gap-fc"] == 2


def test_streak_ignores_stale_club_master_current_tier():
    # club_master says tier 3 (hand-maintained, stale), but the club's own
    # standings history shows tier 4 for its two most recent seasons.
    # Streak calculation must use observed data, not club_master.current_tier.
    conn = _make_db([("stale-fc", 3, [(2023, 4), (2024, 4)])])
    assert _compute_tier_streaks(conn)["stale-fc"] == 2
