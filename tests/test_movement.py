import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from movement import (
    PROMOTION_BACK_TO_BACK,
    PROMOTION_PAUSED,
    PROMOTION_THREE_PLUS,
    RELEGATION_BACK_TO_BACK,
    RELEGATION_HELD,
    RELEGATION_SANDWICH,
    RELEGATION_THREE_PLUS,
    classify,
    detect_patterns,
)


# ── Event classification ────────────────────────────────────────────────

def test_promotion_and_relegation_statuses():
    assert classify(2, "Promoted") == "promotion"
    assert classify(3, "Play-off Promoted") == "promotion"
    assert classify(2, "Champions") == "promotion"
    assert classify(1, "Relegated") == "relegation"
    assert classify(4, "Stayed") == "stay"


def test_tier1_champions_is_not_a_promotion():
    # There's no tier above the Premier League to move up into.
    assert classify(1, "Champions") == "stay"


# ── Run-length patterns ─────────────────────────────────────────────────

def test_back_to_back_relegation():
    history = [(2016, 1, "Stayed"), (2017, 1, "Relegated"), (2018, 2, "Relegated"),
               (2019, 3, "Stayed")]
    matches = detect_patterns(history)
    assert matches == [
        {"pattern": RELEGATION_BACK_TO_BACK, "seasons": [2017, 2018], "tiers": [1, 2]}
    ]


def test_sunderlands_real_history_yields_exactly_one_match():
    # Sunderland's actual 1994-2026 standings rows (data/db/england.db) -
    # the real double relegation that prompted this whole feature.
    history = [
        (1994, 2, "Stayed"), (1995, 2, "Stayed"), (1996, 2, "Champions"),
        (1997, 1, "Relegated"), (1998, 2, "Stayed"), (1999, 2, "Champions"),
        (2000, 1, "Stayed"), (2001, 1, "Stayed"), (2002, 1, "Stayed"),
        (2003, 1, "Relegated"), (2004, 2, "Stayed"), (2005, 2, "Play-off Promoted"),
        (2006, 1, "Relegated"), (2007, 2, "Champions"), (2008, 1, "Stayed"),
        (2009, 1, "Stayed"), (2010, 1, "Stayed"), (2011, 1, "Stayed"),
        (2012, 1, "Stayed"), (2013, 1, "Stayed"), (2014, 1, "Stayed"),
        (2015, 1, "Stayed"), (2016, 1, "Stayed"), (2017, 1, "Relegated"),
        (2018, 2, "Relegated"), (2019, 3, "Stayed"), (2020, 3, "Stayed"),
        (2021, 3, "Stayed"), (2022, 3, "Play-off Promoted"), (2023, 2, "Stayed"),
        (2024, 2, "Stayed"), (2025, 2, "Play-off Promoted"), (2026, 1, "Stayed"),
    ]
    assert detect_patterns(history) == [
        {"pattern": RELEGATION_BACK_TO_BACK, "seasons": [2017, 2018], "tiers": [1, 2]}
    ]


def test_three_relegations_in_a_row_not_also_reported_as_back_to_back():
    history = [(2010, 1, "Relegated"), (2011, 2, "Relegated"), (2012, 3, "Relegated"),
               (2013, 4, "Stayed")]
    matches = detect_patterns(history)
    assert matches == [
        {"pattern": RELEGATION_THREE_PLUS, "seasons": [2010, 2011, 2012],
         "tiers": [1, 2, 3]}
    ]


def test_four_in_a_row_reported_once_with_every_season():
    history = [(2008, 5, "Promoted"), (2009, 4, "Promoted"), (2010, 3, "Promoted"),
               (2011, 2, "Promoted"), (2012, 1, "Stayed")]
    matches = detect_patterns(history)
    assert matches == [
        {"pattern": PROMOTION_THREE_PLUS, "seasons": [2008, 2009, 2010, 2011],
         "tiers": [5, 4, 3, 2]}
    ]


def test_back_to_back_promotion():
    history = [(2019, 4, "Stayed"), (2020, 4, "Promoted"), (2021, 3, "Promoted"),
               (2022, 2, "Stayed")]
    matches = detect_patterns(history)
    assert matches == [
        {"pattern": PROMOTION_BACK_TO_BACK, "seasons": [2020, 2021], "tiers": [4, 3]}
    ]


# ── Three-season middle-event patterns ──────────────────────────────────

def test_relegation_held_then_relegated_again():
    history = [(2000, 1, "Relegated"), (2001, 2, "Stayed"), (2002, 2, "Relegated"),
               (2003, 3, "Stayed")]
    matches = detect_patterns(history)
    assert matches == [
        {"pattern": RELEGATION_HELD, "seasons": [2000, 2001, 2002], "tiers": [1, 2, 2]}
    ]


def test_relegation_sandwiched_by_a_promotion():
    history = [(2000, 1, "Relegated"), (2001, 2, "Promoted"), (2002, 1, "Relegated"),
               (2003, 2, "Stayed")]
    matches = detect_patterns(history)
    assert matches == [
        {"pattern": RELEGATION_SANDWICH, "seasons": [2000, 2001, 2002], "tiers": [1, 2, 1]}
    ]


def test_promotion_paused_then_promoted_again():
    history = [(2000, 4, "Promoted"), (2001, 3, "Stayed"), (2002, 3, "Promoted"),
               (2003, 2, "Stayed")]
    matches = detect_patterns(history)
    assert matches == [
        {"pattern": PROMOTION_PAUSED, "seasons": [2000, 2001, 2002], "tiers": [4, 3, 3]}
    ]


def test_relegation_then_stay_then_promotion_matches_nothing():
    # A relegation followed by a stay and a promotion isn't any of the
    # seven tracked patterns - it's just an ordinary bounce-back.
    history = [(2000, 1, "Relegated"), (2001, 2, "Stayed"), (2002, 2, "Promoted")]
    assert detect_patterns(history) == []


# ── Contiguity ───────────────────────────────────────────────────────────

def test_gap_in_seasons_breaks_a_would_be_back_to_back():
    # Relegated in 2010, then again in 2012 - but the club is missing from
    # the standings table for 2011 (e.g. a spell below Tier 5), so this is
    # not a genuine back-to-back and must not match.
    history = [(2010, 1, "Relegated"), (2012, 3, "Relegated")]
    assert detect_patterns(history) == []


def test_gap_breaks_a_three_season_middle_event_pattern():
    history = [(2010, 1, "Relegated"), (2012, 2, "Stayed"), (2013, 2, "Relegated")]
    assert detect_patterns(history) == []


# ── Trivial inputs ───────────────────────────────────────────────────────

def test_short_or_uneventful_history_yields_no_matches():
    assert detect_patterns([]) == []
    assert detect_patterns([(2020, 1, "Stayed")]) == []
    assert detect_patterns(
        [(2020, 1, "Stayed"), (2021, 1, "Stayed"), (2022, 1, "Stayed")]
    ) == []


# ── Loading from the database ───────────────────────────────────────────

def test_load_status_histories_reads_standings(tmp_path):
    import sqlite3
    from movement import load_status_histories

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE standings (club_id TEXT, season_end_year INT, tier INT, status TEXT)"
    )
    conn.executemany(
        "INSERT INTO standings VALUES (?, ?, ?, ?)",
        [
            ("club-b", 2001, 2, "Stayed"),
            ("club-a", 2000, 1, "Relegated"),
            ("club-a", 1999, 1, "Stayed"),
        ],
    )
    conn.commit()

    histories = load_status_histories(conn)
    assert histories["club-a"] == [(1999, 1, "Stayed"), (2000, 1, "Relegated")]
    assert histories["club-b"] == [(2001, 2, "Stayed")]
