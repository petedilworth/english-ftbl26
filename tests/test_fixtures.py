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


# ── Byte-level decoding ────────────────────────────────────────────────
# The in-memory DataFrame tests above never exercise the decode path, which
# is how the BOM bug reached production: the file parsed "fine" and simply
# yielded no fixtures every week.

BOM = b"\xef\xbb\xbf"
CSV_BODY = (
    b"Div,Date,Time,HomeTeam,AwayTeam,Referee\n"
    b"E0,15/08/2026,15:00,Arsenal,Chelsea,A Taylor\n"
    b"EC,12/08/2026,19:45,Barnet,Arsenal,B Smith\n"
    b"SP1,15/08/2026,20:00,Barcelona,Getafe,C Jones\n"
)


def _parse_bytes(raw, **kwargs):
    import io

    import pandas as pd

    df = pd.read_csv(
        io.BytesIO(raw), encoding="utf-8-sig", encoding_errors="replace",
        on_bad_lines="skip",
    )
    return parse_fixtures(df, RESOLVER, today=TODAY, **kwargs)


def test_bom_prefixed_file_still_finds_the_div_column():
    # Regression: with encoding="latin-1" the BOM made column 1 'ï»¿Div',
    # so Div went missing while Date/HomeTeam/AwayTeam survived - and the
    # digest reported "no fixtures" every single week.
    result = _parse_bytes(BOM + CSV_BODY)
    assert [f["div"] for f in result] == ["E0", "EC"]  # SP1 filtered out


def test_file_without_bom_also_works():
    result = _parse_bytes(CSV_BODY)
    assert [f["div"] for f in result] == ["E0", "EC"]


def test_bom_survives_a_wrong_codec_via_column_cleaning():
    """Even if the codec is wrong, cleaning column names rescues the parse."""
    import io

    import pandas as pd

    df = pd.read_csv(io.BytesIO(BOM + CSV_BODY), encoding="latin-1")
    assert "Div" not in df.columns          # the original failure mode
    result = parse_fixtures(df, RESOLVER, today=TODAY)
    assert [f["div"] for f in result] == ["E0", "EC"]


def test_optional_referee_column_absent_is_fine():
    # The live file has been seen both with and without Referee
    raw = (
        b"Div,Date,Time,HomeTeam,AwayTeam\n"
        b"E0,15/08/2026,15:00,Arsenal,Chelsea\n"
    )
    assert len(_parse_bytes(BOM + raw)) == 1


def test_header_only_file_yields_no_fixtures():
    # Off-season: a rolling window with nothing in it is normal, not an error
    assert _parse_bytes(BOM + b"Div,Date,Time,HomeTeam,AwayTeam\n") == []
