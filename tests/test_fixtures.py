import datetime
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fixtures import current_season_end_year, parse_fixtures

RESOLVER = {"arsenal": "arsenal-fc", "chelsea": "chelsea-fc", "barnet": "barnet-fc"}

TODAY = datetime.date(2026, 8, 10)  # a Monday in early season


def _df(rows):
    return pd.DataFrame(rows, columns=["Div", "Date", "Time", "HomeTeam", "AwayTeam"])


def test_season_end_year_rolls_in_july():
    assert current_season_end_year(datetime.date(2026, 6, 30)) == 2026
    assert current_season_end_year(datetime.date(2026, 7, 1)) == 2027
    assert current_season_end_year(datetime.date(2026, 12, 25)) == 2027


def test_window_and_division_filtering():
    df = _df([
        ("E0", "15/08/2026", "15:00", "Arsenal", "Chelsea"),   # in window
        ("E0", "25/08/2026", "15:00", "Chelsea", "Arsenal"),   # beyond window
        ("SP1", "15/08/2026", "15:00", "Barcelona", "Getafe"), # wrong league
        ("EC", "12/08/2026", "19:45", "Barnet", "Arsenal"),    # tier 5, in window
    ])
    result = parse_fixtures(df, RESOLVER, today=TODAY, window_days=8)
    assert len(result) == 2
    assert result[0]["tier"] == 1
    assert result[1]["tier"] == 5
    assert result[0]["home_id"] == "arsenal-fc"


def test_unresolved_names_kept_with_none_id():
    df = _df([("E0", "15/08/2026", "", "Mystery Town", "Arsenal")])
    result = parse_fixtures(df, RESOLVER, today=TODAY)
    assert len(result) == 1
    assert result[0]["home_id"] is None
    assert result[0]["away_id"] == "arsenal-fc"


def test_bad_dates_dropped():
    df = _df([("E0", "not a date", "", "Arsenal", "Chelsea")])
    assert parse_fixtures(df, RESOLVER, today=TODAY) == []
