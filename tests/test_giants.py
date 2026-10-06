"""Fallen giants & risers: falls from the title, return odds, speed, risers."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import giants  # noqa: E402


def _db(rows):
    """rows: (club_id, season, tier, status)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE standings (club_id TEXT, season_end_year INT, tier INT, status TEXT, position INT,"
                 " played INT, points INT, division_name TEXT)")
    conn.execute("CREATE TABLE club_master (club_id TEXT, canonical_name TEXT)")
    for cid in {r[0] for r in rows}:
        conn.execute("INSERT INTO club_master VALUES (?, ?)", (cid, cid.title()))
    conn.executemany("INSERT INTO standings (club_id, season_end_year, tier, status, position, played, points,"
                     " division_name) VALUES (?,?,?,?,1,10,20,'Div')", rows)
    return conn


def _career(cid, tiers, start=2000, champion=None):
    return [(cid, start + i, t, "Champions" if start + i == champion else "Stayed") for i, t in enumerate(tiers)]


def test_a_champion_who_falls_is_timed_from_the_title():
    conn = _db(_career("fox", [1, 1, 2, 2, 3, 3], champion=2001))
    hist = giants.histories(conn)
    c = giants.champions_fell(conn, hist, 2005)
    assert len(c) == 1 and c[0]["title"] == 2001 and c[0]["reached"] == 2004 and c[0]["years"] == 3
    assert c[0]["path"][0] == [0, 1] and c[0]["low"] == 3


def test_return_odds_leave_out_relegations_too_recent_to_judge():
    hist = {"a": {2000: 1, 2001: 2, 2002: 1},              # out one season, back
            "b": {2000: 1, 2001: 2, 2002: 2, 2003: 2},      # out, not back
            "c": {2009: 1, 2010: 2}}                         # out last season: too recent for k=2
    events = giants.relegations(hist)
    assert {(e["club_id"], e["away"]) for e in events} == {("a", 1), ("b", None), ("c", None)}
    odds = {r["k"]: r for r in giants.return_odds(events, latest=2011, horizon=3)}
    assert odds[1]["n"] == 3 and odds[1]["within"] == pytest.approx(1 / 3, abs=1e-3)
    assert odds[2]["n"] == 2                                 # c has run only one finished season
    assert giants.chance_for(1, giants.return_odds(events, 2011, 3), min_n=1)["k"] == 1


def test_fastest_falls_and_rises():
    hist = {"drop": {2000: 1, 2001: 2, 2002: 3, 2003: 4},
            "climb": {2000: 5, 2001: 4, 2002: 3, 2003: 2, 2004: 1}}
    f = giants.fastest(hist)
    assert f["falls"][0]["club_id"] == "drop" and f["falls"][0]["years"] == 3
    assert f["rises"][0]["club_id"] == "climb" and f["rises"][0]["years"] == 3     # from tier 4 in 2001
    assert f["from_five"][0]["years"] == 4


def test_risers_count_from_the_most_recent_low_point():
    hist = {"up": {2000: 4, 2001: 3, 2002: 4, 2003: 3, 2004: 2},
            "never": {2000: 3, 2001: 2}}
    r = giants.risers(hist, latest=2004)
    assert [x["club_id"] for x in r] == ["up"] and r[0]["low_at"] == 2002 and r[0]["years"] == 2


def test_assemble_finds_this_seasons_fallen_and_their_mood():
    rows = _career("fox", [1, 1, 2, 3, 3], champion=2001) + _career("hare", [2, 2, 2, 2, 1])
    d = giants.assemble(_db(rows), with_size=False)
    assert [f["club_id"] for f in d["fallen"]] == ["fox"] and d["fallen"][0]["away"] == 3
    assert d["live"][0]["club_id"] == "fox" and d["live"][0]["mood"] in ("climbing", "holding", "sinking")
    assert d["champions"][0]["name"] == "Fox"
