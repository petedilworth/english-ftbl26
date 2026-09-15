"""
club_streak_records and result_bands: a club's results against its own past.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import records  # noqa: E402


def _db(matches):
    """matches: (season, date_or_None, home, away, hg, ag[, tier])"""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE matches (season_end_year INT, tier INT, match_date TEXT,"
        " home_club_id TEXT, away_club_id TEXT, home_name TEXT, away_name TEXT,"
        " fthg INT, ftag INT, ftr TEXT, division_id TEXT)"
    )
    for m in matches:
        season, date, home, away, hg, ag = m[:6]
        tier = m[6] if len(m) > 6 else 3
        ftr = "H" if hg > ag else "A" if hg < ag else "D"
        conn.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (season, tier, date, home, away, home, away, hg, ag, ftr, "d"))
    records.rebuild_records(conn)
    return conn


def _season(season, club, results, start_month=8, opp="opp-fc"):
    """A run of results for `club`, one a week from August. 'W', 'D', 'L'."""
    out = []
    for i, r in enumerate(results):
        day = 1 + i * 7
        date = f"{season - 1}-{start_month + day // 30:02d}-{day % 30 + 1:02d}"
        hg, ag = {"W": (2, 0), "D": (1, 1), "L": (0, 2)}[r]
        out.append((season, date, club, opp, hg, ag))
    return out


def _streak(conn, club, kind):
    return conn.execute(
        "SELECT record_length, current_length, since_season FROM club_streak_records"
        " WHERE club_id=? AND streak_type=?", (club, kind)).fetchone()


def _bands(conn, club, kind=None):
    sql = "SELECT band, since_season, detail FROM result_bands WHERE club_id=?"
    args = [club]
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    return conn.execute(sql + " ORDER BY match_date", args).fetchall()


# ── streaks ────────────────────────────────────────────────────────────────

def test_record_and_live_run():
    conn = _db(_season(2020, "a-fc", "WWWLWW"))
    assert _streak(conn, "a-fc", "win") == (3, 2, 2020)
    assert _streak(conn, "a-fc", "unbeaten") == (3, 2, 2020)
    assert _streak(conn, "a-fc", "loss") == (1, 0, 2020)
    assert _streak(conn, "a-fc", "clean_sheet") == (3, 2, 2020)
    # the opponent's record is the mirror
    assert _streak(conn, "opp-fc", "loss") == (3, 2, 2020)


def test_a_run_survives_the_summer_between_consecutive_dated_seasons():
    conn = _db(_season(2020, "a-fc", "LWW") + _season(2021, "a-fc", "WWL"))
    assert _streak(conn, "a-fc", "win")[0] == 4


def test_a_run_breaks_at_a_season_gap_or_an_undated_season():
    gap = _db(_season(2020, "a-fc", "LWW") + _season(2022, "a-fc", "WWL"))
    assert _streak(gap, "a-fc", "win")[0] == 2

    undated = _db(_season(2020, "a-fc", "LWW") + _season(2021, "a-fc", "WWL")
                  + [(2021, None, "a-fc", "x-fc", 1, 0)])
    assert _streak(undated, "a-fc", "win")[0] == 2


def test_undated_matches_never_count_towards_a_run():
    conn = _db([(2020, None, "a-fc", "opp-fc", 1, 0)] * 5 + _season(2021, "a-fc", "WW"))
    assert _streak(conn, "a-fc", "win") == (2, 2, 2021)


# ── bands ──────────────────────────────────────────────────────────────────

def test_band_thresholds():
    assert records.band_for(None, 12) == "historic"
    assert records.band_for(None, 7) == "of_note"     # short record: gap is the span
    assert records.band_for(None, 3) is None
    assert records.band_for(10, 30) == "notable"
    assert records.band_for(5, 30) == "of_note"
    assert records.band_for(4, 30) is None


def test_biggest_win_since():
    history = [(2010, "2009-09-01", "a-fc", "b-fc", 5, 0)]
    filler = [_season(s, "a-fc", "DDD")[0] for s in range(2011, 2027)]
    conn = _db(history + filler + [(2027, "2026-09-05", "a-fc", "c-fc", 5, 0)])
    (band, since, detail), = _bands(conn, "a-fc", "margin")
    assert (band, since) == ("notable", 2010)
    assert '"direction": "win"' in detail and '"margin": 5' in detail


def test_a_margin_matched_recently_is_not_news():
    conn = _db(_season(2024, "a-fc", "W") + [(2024, "2023-10-01", "a-fc", "b-fc", 4, 0)]
               + _season(2027, "a-fc", "D") + [(2027, "2026-09-05", "a-fc", "c-fc", 4, 0)])
    assert _bands(conn, "a-fc", "margin") == []


def test_heaviest_defeat_in_the_record_is_historic_only_with_a_long_record():
    long = _db([_season(s, "a-fc", "D")[0] for s in range(2010, 2027)]
               + [(2027, "2026-09-05", "a-fc", "c-fc", 0, 6)])
    (band, since, detail), = _bands(long, "a-fc", "margin")
    assert (band, since) == ("historic", None) and '"defeat"' in detail

    short = _db([_season(s, "a-fc", "D")[0] for s in range(2024, 2027)]
                + [(2027, "2026-09-05", "a-fc", "c-fc", 0, 6)])
    assert _bands(short, "a-fc", "margin") == []


def test_first_win_over_an_opponent_since():
    meetings = [(2012, "2011-09-01", "a-fc", "b-fc", 1, 0)] + [
        (s, f"{s - 1}-09-01", "a-fc", "b-fc", 0, 1) for s in (2015, 2018, 2021, 2024)]
    conn = _db(meetings + [(2027, "2026-09-05", "b-fc", "a-fc", 0, 2)])
    (band, since, detail), = _bands(conn, "a-fc", "opponent")
    assert (band, since) == ("notable", 2012)
    assert '"meetings_before": 5' in detail
    # b-fc get nothing: a defeat is not an opponent band
    assert _bands(conn, "b-fc", "opponent") == []


def test_opponent_band_needs_a_few_earlier_meetings():
    conn = _db([(2012, "2011-09-01", "a-fc", "b-fc", 0, 1)]
               + [(2027, "2026-09-05", "a-fc", "b-fc", 2, 0)])
    assert _bands(conn, "a-fc", "opponent") == []


def test_best_start_since():
    poor = [m for s in range(2016, 2027) for m in _season(s, "a-fc", "LLLLL")]
    conn = _db(poor + _season(2027, "a-fc", "WWWWW"))
    bands = _bands(conn, "a-fc", "start")
    assert bands and all(b == "historic" for b, _, _ in bands)
    assert any('"games": 5' in d and '"points": 15' in d and '"best"' in d for _, _, d in bands)
    # no "worst" band: every earlier season was worse or equal only a year ago
    assert not any('"worst"' in d for _, _, d in bands)


def test_a_run_reaching_a_length_not_seen_for_years():
    conn = _db(_season(2016, "a-fc", "WWWL")
               + [m for s in range(2017, 2027) for m in _season(s, "a-fc", "WLWL")]
               + _season(2027, "a-fc", "WWW"))
    # Three 2-0 wins are also three clean sheets; both runs band. Check the win.
    wins = [b for b in _bands(conn, "a-fc", "streak") if '"streak_type": "win"' in b[2]]
    (band, since, detail), = wins
    assert (band, since) == ("notable", 2016)
    assert '"length": 3' in detail


def test_short_runs_earn_nothing():
    conn = _db([m for s in range(2010, 2027) for m in _season(s, "a-fc", "LL")]
               + _season(2027, "a-fc", "WW"))
    assert _bands(conn, "a-fc", "streak") == []


def test_empty_database_still_gets_both_tables():
    conn = _db([])
    assert conn.execute("SELECT COUNT(*) FROM club_streak_records").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM result_bands").fetchone() == (0,)
