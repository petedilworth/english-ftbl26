"""The odds and match statistics kept from football-data.co.uk files."""

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import match_stats  # noqa: E402
import pipeline  # noqa: E402


def test_the_files_own_average_wins_and_closing_odds_are_kept():
    df = pd.DataFrame([{
        "AvgH": 2.10, "AvgD": 3.40, "AvgA": 3.60, "B365H": 2.00, "B365D": 3.50, "B365A": 3.75,
        "PSH": 2.15, "PSD": 3.45, "PSA": 3.70, "AvgCH": 1.90, "AvgCD": 3.50, "AvgCA": 4.20,
        "HS": 14, "AS": 9, "HST": 6, "AST": 2, "HC": 7, "AC": 3, "HY": 1, "AY": 2, "HR": 0, "AR": 1,
        "HTHG": 1, "HTAG": 0, "Referee": " M Dean "}])
    out = match_stats.extract(df).iloc[0]
    assert (out["mkt_h"], out["mkt_d"], out["mkt_a"]) == (2.10, 3.40, 3.60)
    assert pd.isna(out["mkt_books"])               # the file's average does not say how many
    assert (out["close_h"], out["pin_h"], out["b365_a"]) == (1.90, 2.15, 3.75)
    assert (out["home_sot"], out["away_red"], out["ht_hg"]) == (6, 1, 1)
    assert out["referee"] == "M Dean"


def test_betbrain_average_before_2019_and_a_mean_of_books_before_that():
    bb = match_stats.extract(pd.DataFrame([{"BbAvH": 1.8, "BbAvD": 3.3, "BbAvA": 4.5, "WHH": 1.7, "WHD": 3.2, "WHA": 4.0}]))
    assert bb.iloc[0]["mkt_h"] == 1.8
    early = match_stats.extract(pd.DataFrame([
        {"WHH": 2.0, "WHD": 3.0, "WHA": 3.5, "LBH": 2.2, "LBD": 3.2, "LBA": 3.3, "IWH": 2.1, "IWD": None, "IWA": 3.0},
    ])).iloc[0]
    # Interwetten has no draw price, so it is not a price at all; two books remain.
    assert early["mkt_h"] == pytest.approx(2.1) and early["mkt_books"] == 2
    assert pd.isna(early["pin_h"]) and pd.isna(early["close_h"])


def test_a_row_with_no_odds_or_statistics_yields_nothing():
    df = pd.DataFrame([{"HomeTeam": "A", "AwayTeam": "B", "FTHG": 1, "FTAG": 0, "FTR": "H"}])
    matches = df.assign(match_date=None)
    assert match_stats.rows_for(df, matches, 1970, 1, "x", lambda n: n) == []


def test_the_pipeline_stores_them_beside_the_match_and_replaces_a_season(tmp_path):
    csv = tmp_path / "2324_E0.csv"
    header = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HS,AS,HST,AST,Referee,B365H,B365D,B365A,AvgH,AvgD,AvgA\n"
    csv.write_text(header
                   + "E0,12/08/2023,Burnley,Man City,0,3,A,6,17,1,8,C Pawson,8.0,5.25,1.33,8.5,5.3,1.34\n"
                   + "E0,12/08/2023,Arsenal,Forest,2,1,H,15,6,7,2,M Oliver,1.2,7.0,13.0,1.21,6.9,13.5\n")
    conn = sqlite3.connect(":memory:")
    conn.execute(pipeline.CREATE_STANDINGS_SQL)
    conn.execute(pipeline.CREATE_MATCHES_SQL)
    resolver = {}
    for _ in range(2):                       # a re-run replaces, it does not add
        pipeline._process_season(conn, csv, 2024, 1, resolver, defaultdict(list))
    rows = conn.execute("SELECT home_name, match_date, mkt_a, b365_h, home_sot, away_sot, referee"
                        " FROM match_stats ORDER BY home_name").fetchall()
    assert rows == [("Arsenal", "2023-08-12", 13.5, 1.2, 7, 2, "M Oliver"),
                    ("Burnley", "2023-08-12", 1.34, 8.0, 1, 8, "C Pawson")]
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 2
