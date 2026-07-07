import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aggregate import compute_standings, get_division_name


def _matches(rows):
    return pd.DataFrame(rows, columns=["HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"])


def test_points_and_positions():
    # A beats B 2-0, B beats C 1-0, A draws C 1-1
    df = _matches([
        ("A", "B", 2, 0, "H"),
        ("B", "C", 1, 0, "H"),
        ("A", "C", 1, 1, "D"),
    ])
    standings = compute_standings(df, 2024, 1).set_index("club_name")
    assert standings.loc["A", "points"] == 4
    assert standings.loc["B", "points"] == 3
    assert standings.loc["C", "points"] == 1
    assert standings.loc["A", "position"] == 1
    assert standings.loc["B", "position"] == 2
    assert standings.loc["C", "position"] == 3


def test_tiebreak_by_goal_difference_then_goals_for():
    # A and B both finish on 3 points; A has better GD.
    df = _matches([
        ("A", "C", 3, 0, "H"),
        ("B", "C", 1, 0, "H"),
    ])
    standings = compute_standings(df, 2024, 1).set_index("club_name")
    assert standings.loc["A", "position"] == 1
    assert standings.loc["B", "position"] == 2


def test_wdl_and_goals():
    df = _matches([
        ("A", "B", 2, 1, "H"),
        ("B", "A", 2, 2, "D"),
    ])
    standings = compute_standings(df, 2024, 1).set_index("club_name")
    assert standings.loc["A", "won"] == 1
    assert standings.loc["A", "drawn"] == 1
    assert standings.loc["A", "lost"] == 0
    assert standings.loc["A", "gf"] == 4
    assert standings.loc["A", "ga"] == 3
    assert standings.loc["A", "gd"] == 1
    assert standings.loc["A", "played"] == 2


def test_division_names():
    assert get_division_name(2, 2003) == "First Division"
    assert get_division_name(2, 2004) == "Championship"
    assert get_division_name(5, 2010) == "Conference Premier"
    assert get_division_name(5, 2020) == "National League"
