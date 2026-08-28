import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

import aggregate
import download
import historical
import pipeline


def test_two_digit_seasons_resolve_either_side_of_the_pivot():
    # The pivot used to sit at 94, the earliest season football-data.co.uk
    # publishes, so '5859' read as 2059 and the backfilled files were
    # silently skipped as out-of-range.
    assert download.str_to_season("5859") == 1959
    assert download.str_to_season("9293") == 1993
    assert download.str_to_season("9394") == 1994
    assert download.str_to_season("2627") == 2027
    for year in (1959, 1975, 1993, 1994, 2001, 2027):
        assert download.str_to_season(download.season_to_str(year)) == year


def test_points_for_win_changes_in_1981_82():
    assert aggregate.points_for_win(1981) == 2
    assert aggregate.points_for_win(1982) == 3
    assert aggregate.points_for_win(2026) == 3


def test_historical_filenames_are_distinguishable_from_downloads():
    # standings.source must not credit football-data.co.uk with seasons it
    # never published, so the two kinds of file have to be tellable apart.
    name = historical.historical_filename(1959, 1)
    assert pipeline._parse_filename(name) == (1959, 1, None, True)
    assert pipeline._parse_filename("9394_E0.csv") == (1994, 1, None, False)
    # A file below the fifth tier names its division, because the tier is
    # several of them.
    assert pipeline._parse_filename("1213_national-league-north_nl.csv") == (
        2013, 6, "national-league-north", True)
    assert pipeline._build_source(1959, 1, is_historical=True).startswith(
        historical.SOURCE_NAME)
    assert "football-data" in pipeline._build_source(1994, 1)


def _source_csv(tmp_path, rows):
    path = tmp_path / historical.CACHE_NAME
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "Season", "home", "visitor", "FT", "hgoal",
                    "vgoal", "division", "tier", "totgoal", "goaldif", "result"])
        for r in rows:
            w.writerow(r)
    return path


def test_convert_emits_football_data_shape(tmp_path):
    src = _source_csv(tmp_path, [
        ["1958-08-23", 1958, "Aston Villa", "Birmingham City", "1-1", 1, 1, "1", 1, 2, 0, "D"],
        ["1958-08-23", 1958, "Bolton Wanderers", "Leeds United", "4-0", 4, 0, "1", 1, 4, 4, "H"],
    ])
    written = historical.convert(src, tmp_path, 1959, 1959)
    assert len(written) == 1
    rows = list(csv.DictReader(open(written[0], encoding="utf-8")))
    assert [r["Div"] for r in rows] == ["E0", "E0"]
    assert rows[0]["HomeTeam"] == "Aston Villa"
    assert rows[0]["Date"] == "23/08/1958"      # dayfirst, as the loader expects
    assert rows[1]["FTR"] == "H"


def test_convert_refuses_the_regional_third_division_era(tmp_path):
    # Before 1958/59 the third tier was two parallel divisions, which this
    # schema has no way to hold. Failing loudly beats merging them.
    src = _source_csv(tmp_path, [])
    with pytest.raises(ValueError, match="regional"):
        historical.convert(src, tmp_path, 1950, 1955)


def test_regional_rows_are_dropped_rather_than_merged(tmp_path):
    src = _source_csv(tmp_path, [
        ["1958-08-23", 1958, "A", "B", "1-0", 1, 0, "3N", 3, 1, 1, "H"],
        ["1958-08-23", 1958, "C", "D", "2-0", 2, 0, "3S", 3, 2, 2, "H"],
    ])
    assert historical.convert(src, tmp_path, 1959, 1959) == []


def test_override_seasons_are_emitted_outside_the_historical_range(tmp_path):
    # The known-bad football-data seasons sit after the backfill range, so
    # convert() has to reach past its own ceiling for exactly those.
    season, tier = next(iter(historical.OVERRIDES))
    src = _source_csv(tmp_path, [
        [f"{season - 1}-08-23", season - 1, "A", "B", "1-0", 1, 0,
         str(tier), tier, 1, 1, "H"],
    ])
    written = historical.convert(src, tmp_path, 1959, 1993)
    assert [p.name for p in written] == [historical.historical_filename(season, tier)]


# ── the sixth and seventh tiers ────────────────────────────────────────

def _nl_row(home, visitor, date, ft="1-0", season=2016, tier="6", division="N"):
    hg, vg = ft.split("-")
    return {"Date": date, "Season": str(season), "home": home, "visitor": visitor,
            "FT": ft, "hgoal": hg, "vgoal": vg, "division": division,
            "tier": tier, "result": "H"}


def test_a_division_letter_means_different_things_in_different_seasons():
    """
    'S' at the seventh tier is the Southern League Premier until 2017/18
    and its southern half from 2018/19, when the division split in two.
    A mapping that ignores the season files six seasons under the wrong
    division.
    """
    assert historical.nonleague_division_id(7, "S", 2015) == "southern-league-premier"
    assert historical.nonleague_division_id(7, "S", 2019) == "southern-league-premier-south"
    assert historical.nonleague_division_id(6, "N", 2015) == "national-league-north"
    assert historical.nonleague_division_id(6, "X", 2015) is None


def test_a_play_off_tie_is_not_a_league_match():
    """
    A round-robin holds one meeting per ordered pair. A second one in May
    is a play-off, and counting it awards points that were never league
    points.
    """
    rows = [_nl_row("Chorley", "Kidderminster Harriers", "2017-01-14"),
            _nl_row("Chorley", "Kidderminster Harriers", "2017-05-03", ft="2-1")]
    kept = historical._drop_repeat_fixtures(rows, "test")
    assert len(kept) == 1
    assert kept[0]["Date"] == "2017-01-14"


def test_the_date_decides_before_the_score_does():
    """
    FC Halifax Town beat Chorley 2-1 in the 2016/17 play-off final having
    also beaten them 2-1 in January. Testing the score first would call a
    play-off a double entry and say so in the log.
    """
    rows = [_nl_row("FC Halifax Town", "Chorley", "2017-01-10", ft="2-1"),
            _nl_row("FC Halifax Town", "Chorley", "2017-05-13", ft="2-1")]
    kept = historical._drop_repeat_fixtures(rows, "test")
    assert len(kept) == 1 and kept[0]["Date"] == "2017-01-10"


def test_a_december_repeat_is_not_a_play_off():
    """
    The window is compared as month-day, because "12-15" is after "04-20"
    on a plain string or numeric reading and December is not May. Swindon
    Supermarine v Basingstoke Town is the real case.
    """
    rows = [_nl_row("Swindon Supermarine", "Basingstoke Town", "2018-10-16", ft="4-2"),
            _nl_row("Swindon Supermarine", "Basingstoke Town", "2018-12-15", ft="5-2")]
    kept = historical._drop_repeat_fixtures(rows, "test")
    assert len(kept) == 1
    lo, hi = historical.PLAYOFF_WINDOW
    assert not lo <= "12-15" <= hi


def test_an_ordinary_season_loses_nothing():
    rows = [_nl_row("A", "B", "2016-09-01"), _nl_row("B", "A", "2017-02-01"),
            _nl_row("A", "C", "2016-10-01"), _nl_row("C", "A", "2017-03-01")]
    assert len(historical._drop_repeat_fixtures(rows, "test")) == 4
