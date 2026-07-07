import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from status import assign_status, get_rules


def _standings(n_clubs, season, tier):
    return pd.DataFrame(
        {"position": range(1, n_clubs + 1), "tier": tier, "season_end_year": season}
    )


def _status_at(df, pos):
    return df.set_index("position").loc[pos, "status"]


def test_premier_league_modern():
    df = assign_status(_standings(20, 2024, 1), 2024, 1)
    assert _status_at(df, 1) == "Champions"
    assert _status_at(df, 2) == "Stayed"
    assert _status_at(df, 17) == "Stayed"
    assert _status_at(df, 18) == "Relegated"
    assert _status_at(df, 20) == "Relegated"


def test_premier_league_1995_four_relegated():
    df = assign_status(_standings(22, 1995, 1), 1995, 1)
    assert _status_at(df, 18) == "Stayed"
    assert _status_at(df, 19) == "Relegated"
    assert _status_at(df, 22) == "Relegated"


def test_championship_modern():
    df = assign_status(_standings(24, 2024, 2), 2024, 2)
    assert _status_at(df, 1) == "Champions"
    assert _status_at(df, 2) == "Promoted"
    assert _status_at(df, 3) == "Play-off Promoted"
    assert _status_at(df, 6) == "Play-off Promoted"
    assert _status_at(df, 7) == "Stayed"
    assert _status_at(df, 21) == "Stayed"
    assert _status_at(df, 22) == "Relegated"


def test_league_one_playoffs_are_3_to_6():
    df = assign_status(_standings(24, 2024, 3), 2024, 3)
    assert _status_at(df, 6) == "Play-off Promoted"
    assert _status_at(df, 7) == "Stayed"
    assert _status_at(df, 20) == "Stayed"
    assert _status_at(df, 21) == "Relegated"


def test_league_two_three_auto_promoted_two_relegated():
    df = assign_status(_standings(24, 2024, 4), 2024, 4)
    assert _status_at(df, 2) == "Promoted"
    assert _status_at(df, 3) == "Promoted"
    assert _status_at(df, 4) == "Play-off Promoted"
    assert _status_at(df, 7) == "Play-off Promoted"
    assert _status_at(df, 8) == "Stayed"
    assert _status_at(df, 22) == "Stayed"
    assert _status_at(df, 23) == "Relegated"
    assert _status_at(df, 24) == "Relegated"


def test_league_two_one_relegated_before_2003():
    df = assign_status(_standings(24, 2002, 4), 2002, 4)
    assert _status_at(df, 23) == "Stayed"
    assert _status_at(df, 24) == "Relegated"


def test_national_league_playoff_expansion_2018():
    old = assign_status(_standings(24, 2017, 5), 2017, 5)
    new = assign_status(_standings(24, 2018, 5), 2018, 5)
    assert _status_at(old, 6) == "Stayed"
    assert _status_at(new, 6) == "Play-off Promoted"
    assert _status_at(new, 7) == "Play-off Promoted"


def test_covid_2021_national_league_no_relegation():
    df = assign_status(_standings(23, 2021, 5), 2021, 5)
    assert (df["status"] == "Relegated").sum() == 0


def test_get_rules_picks_most_specific():
    assert get_rules(4, 2020)["auto_relegate"] == (24, 24)
    assert get_rules(4, 2021)["auto_relegate"] == (23, 24)
