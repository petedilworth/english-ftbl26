import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from download import TIER_TO_CODE, build_url, season_to_str, str_to_season


def test_season_to_str():
    assert season_to_str(1994) == "9394"
    assert season_to_str(2000) == "9900"
    assert season_to_str(2001) == "0001"
    assert season_to_str(2010) == "0910"
    assert season_to_str(2024) == "2324"


def test_round_trip():
    for year in range(1994, 2040):
        assert str_to_season(season_to_str(year)) == year


def test_tier5_uses_conference_code():
    assert TIER_TO_CODE[5] == "EC"
    assert build_url(2019, 5).endswith("/1819/EC.csv")
