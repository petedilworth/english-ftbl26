import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import aggregate
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


# --- Era-aware tiebreaks -------------------------------------------------
#
# Clubs level on points have been separated three different ways, and the
# choice decides championships, not just mid-table order.

def test_tiebreak_rule_eras():
    # Goal average until the end of 1975/76, goal difference after it.
    assert aggregate.tiebreak_rule(1, 1976) == "goal_average"
    assert aggregate.tiebreak_rule(1, 1977) == "goal_difference"

    # The Football League put goals scored first from 1992/93 to 1998/99.
    assert aggregate.tiebreak_rule(2, 1993) == "goals_scored"
    assert aggregate.tiebreak_rule(4, 1997) == "goals_scored"
    assert aggregate.tiebreak_rule(4, 1999) == "goals_scored"
    assert aggregate.tiebreak_rule(2, 2000) == "goal_difference"

    # The Premier League never used it, and neither did the Conference.
    assert aggregate.tiebreak_rule(1, 1997) == "goal_difference"
    assert aggregate.tiebreak_rule(5, 1997) == "goal_difference"


def _two_club_table(a, b):
    """Two clubs level on points, given as (club_id, gf, ga)."""
    rows = []
    for club_id, gf, ga in (a, b):
        rows.append({
            "club_id": club_id, "club_name": club_id, "played": 46,
            "won": 0, "drawn": 0, "lost": 0,
            "gf": gf, "ga": ga, "gd": gf - ga, "points": 87,
        })
    return pd.DataFrame(rows)


def test_goals_scored_tiebreak_gives_wigan_the_1997_title():
    # The real Third Division table of 1996/97. Fulham had the better goal
    # difference; Wigan had scored more and were champions.
    table = _two_club_table(("wigan-athletic-fc", 84, 51), ("fulham-fc", 72, 38))
    ranked = aggregate.rank_standings(table, tier=4, season_end_year=1997)
    assert list(ranked["club_id"]) == ["wigan-athletic-fc", "fulham-fc"]

    # Under the modern rule the same table comes out the other way, which is
    # exactly the error this guards against.
    ranked = aggregate.rank_standings(table, tier=4, season_end_year=2000)
    assert list(ranked["club_id"]) == ["fulham-fc", "wigan-athletic-fc"]


def test_goal_average_can_beat_goal_difference():
    # 60/30 is a goal average of 2.00 and a difference of +30; 45/20 is an
    # average of 2.25 and a difference of only +25. Pre-1977 the second club
    # finishes above; afterwards it does not.
    table = _two_club_table(("big-scorer-fc", 60, 30), ("mean-defence-fc", 45, 20))
    assert list(aggregate.rank_standings(table, 3, 1970)["club_id"]) == [
        "mean-defence-fc", "big-scorer-fc",
    ]
    assert list(aggregate.rank_standings(table, 3, 1980)["club_id"]) == [
        "big-scorer-fc", "mean-defence-fc",
    ]


def test_rank_standings_without_era_defaults_to_goal_difference():
    table = _two_club_table(("a-fc", 60, 30), ("b-fc", 45, 20))
    assert list(aggregate.rank_standings(table)["club_id"]) == ["a-fc", "b-fc"]


# --- Curtailed seasons ---------------------------------------------------
#
# A season abandoned part-way is ranked on points per game, because the
# clubs did not all play the same number of matches.

def test_settled_on_ppg_covers_only_the_curtailed_divisions():
    # League One, League Two and the National League ended 2019/20 on PPG.
    assert aggregate.settled_on_ppg(3, 2020)
    assert aggregate.settled_on_ppg(4, 2020)
    assert aggregate.settled_on_ppg(5, 2020)
    # The National League did it again the following season.
    assert aggregate.settled_on_ppg(5, 2021)
    # The Premier League and the Championship played 2019/20 to a finish.
    assert not aggregate.settled_on_ppg(1, 2020)
    assert not aggregate.settled_on_ppg(2, 2020)
    # And the EFL played 2020/21 out in full.
    assert not aggregate.settled_on_ppg(4, 2021)


def test_curtailed_season_ranks_on_points_per_game():
    # The real top of League Two in 2019/20. Crewe and Swindon finished
    # level on 69 points, but Swindon had played a game fewer, and the
    # title was awarded on points per game.
    table = pd.DataFrame([
        {"club_id": "crewe-alexandra-fc", "played": 37, "points": 69,
         "gd": 24, "gf": 67, "ga": 43},
        {"club_id": "swindon-town-fc", "played": 36, "points": 69,
         "gd": 23, "gf": 62, "ga": 39},
        {"club_id": "plymouth-argyle-fc", "played": 37, "points": 68,
         "gd": 22, "gf": 61, "ga": 39},
    ])
    ranked = aggregate.rank_standings(table.copy(), tier=4, season_end_year=2020)
    assert list(ranked["club_id"])[0] == "swindon-town-fc"

    # Ranked as an ordinary season on points and goal difference, the same
    # table hands the title to Crewe. That is the error this guards against:
    # Swindon's advantage is entirely in having played one game fewer.
    ranked = aggregate.rank_standings(table.copy(), tier=4, season_end_year=2019)
    assert list(ranked["club_id"])[0] == "crewe-alexandra-fc"
