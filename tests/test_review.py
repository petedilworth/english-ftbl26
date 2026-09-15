"""
The Monday and Tuesday reviews: the reckoning, the results that moved
history, the grid with movement, the streak watch, the alternate table.
"""

import datetime
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import records  # noqa: E402
from editions import config, phrasing  # noqa: E402
from editions import review as review_mod  # noqa: E402
from editions.review import ReviewLowerEdition, ReviewTopEdition  # noqa: E402

FRIDAY = datetime.date(2026, 9, 4)
MONDAY = datetime.date(2026, 9, 7)
CLUBS = {"a-fc": "Alpha FC", "b-fc": "Beta United", "c-fc": "Gamma Town", "d-fc": "Delta City"}


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_master (club_id TEXT PRIMARY KEY, canonical_name TEXT,"
                 " name_variants TEXT, lineage_parent_id TEXT, current_tier INT)")
    conn.execute("CREATE TABLE standings (season_end_year INT, tier INT, division_name TEXT,"
                 " club_id TEXT, club_name TEXT, position INT, played INT, won INT, drawn INT,"
                 " lost INT, gf INT, ga INT, gd INT, points INT, status TEXT, source TEXT)")
    conn.execute("CREATE TABLE matches (season_end_year INT, tier INT, match_date TEXT,"
                 " home_club_id TEXT, away_club_id TEXT, home_name TEXT, away_name TEXT,"
                 " fthg INT, ftag INT, ftr TEXT, division_id TEXT)")
    for cid, name in CLUBS.items():
        conn.execute("INSERT INTO club_master VALUES (?,?,NULL,NULL,1)", (cid, name))
    # The table after the weekend: Alpha went top, Beta fell.
    for pos, cid in enumerate(["a-fc", "c-fc", "b-fc", "d-fc"], start=1):
        conn.execute("INSERT INTO standings VALUES (2027,1,'Premier League',?,?,?,5,0,0,0,0,0,0,?,"
                     "'In progress','test')", (cid, CLUBS[cid], pos, 15 - pos))

    def match(season, date, home, away, hg, ag):
        ftr = "H" if hg > ag else "A" if hg < ag else "D"
        conn.execute("INSERT INTO matches VALUES (?,1,?,?,?,?,?,?,?,?,'pl')",
                     (season, date, home, away, CLUBS[home], CLUBS[away], hg, ag, ftr))

    # Alpha's history: a decade of draws, so a 4-0 this weekend is their
    # biggest win in the record. Then a run: three wins into the weekend.
    for season in range(2012, 2027):
        match(season, f"{season - 1}-10-01", "a-fc", "d-fc", 1, 1)
    match(2027, "2026-08-15", "a-fc", "c-fc", 1, 0)
    match(2027, "2026-08-22", "a-fc", "c-fc", 2, 1)
    match(2027, "2026-08-29", "d-fc", "a-fc", 0, 1)
    # The weekend in the window (Sat 5 Sep) and a midweek before it (Tue 1 Sep).
    match(2027, "2026-09-01", "c-fc", "d-fc", 1, 1)
    match(2027, "2026-09-05", "a-fc", "b-fc", 4, 0)
    match(2027, "2026-09-05", "c-fc", "d-fc", 2, 2)
    # Outside the window: the review's own date (the window ends the day before).
    match(2027, "2026-09-07", "c-fc", "d-fc", 0, 0)
    records.rebuild_records(conn)
    return conn


@pytest.fixture
def archive_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARCHIVE_ROOT", tmp_path / "archive")
    monkeypatch.setattr(config, "PREVIEW_ROOT", tmp_path / "preview")
    return tmp_path / "archive"


def _write_claims(archive_root, table=None, claims=None):
    d = archive_root / "preview" / FRIDAY.isoformat()
    d.mkdir(parents=True)
    doc = {"edition": "preview", "date": FRIDAY.isoformat(), "subject": "x",
           "claims": claims if claims is not None else [{
               "fixture": {"tier": 1, "date": "2026-09-05", "home_id": "a-fc", "away_id": "b-fc",
                           "home_name": "Alpha", "away_name": "Beta", "division_name": "Premier League"},
               "speed": "long", "score": 14.0, "reasons": [["top_clash"]],
               "snapshot": {"home": {"club_id": "a-fc", "position": 2},
                            "away": {"club_id": "b-fc", "position": 1}},
           }],
           "table": table if table is not None else {
               "a-fc": {"tier": 1, "position": 2}, "b-fc": {"tier": 1, "position": 1},
               "c-fc": {"tier": 1, "position": 3}, "d-fc": {"tier": 1, "position": 4}}}
    (d / "claims.json").write_text(json.dumps(doc))


def _write_previous_review(archive_root, covered, edition="review-top", days_before=7):
    """The review a week earlier, recording the results it carried."""
    d = archive_root / edition / (MONDAY - datetime.timedelta(days=days_before)).isoformat()
    d.mkdir(parents=True, exist_ok=True)
    (d / "claims.json").write_text(json.dumps({"edition": edition, "claims": [], "covered": covered}))


AUGUST_29 = "2026-08-29|d-fc|a-fc"   # the week before the window: covered by last week's review


def _build(tmp_path, cls=ReviewTopEdition, date=MONDAY, covered=(AUGUST_29,)):
    if covered:
        _write_previous_review(config.ARCHIVE_ROOT, list(covered), cls.name)
    return cls(_db(), date, tmp_path / "charts").build()


def test_the_window_is_the_seven_days_before_and_nothing_else(tmp_path, archive_root):
    out = _build(tmp_path)
    assert "4–0" in out.html and "2–2" in out.html
    assert "Tue 01" in out.html            # the midweek before the weekend
    assert "Mon 07" not in out.html        # the review's own date
    assert out.subject.endswith("3 results")
    assert out.table["a-fc"]["position"] == 1
    assert out.extra["covered"] == sorted([
        "2026-09-01|c-fc|d-fc", "2026-09-05|a-fc|b-fc", "2026-09-05|c-fc|d-fc"])


def test_a_result_nobody_covered_is_caught_up_and_marked_late(tmp_path, archive_root):
    """Sunday's game was not on file when Monday's review built: it turns
    up the following week, flagged, rather than never."""
    _write_previous_review(config.ARCHIVE_ROOT, [])          # a review existed; it carried nothing
    out = ReviewTopEdition(_db(), MONDAY, tmp_path / "charts").build()
    assert out.subject.endswith("4 results")
    assert "Sat 29" in out.html and ">late</span>" in out.html
    assert "2026-08-29|d-fc|a-fc" in out.extra["covered"]
    # and once covered, it is not carried again
    again = _build(tmp_path)
    assert again.subject.endswith("3 results") and "Sat 29" not in again.html


def test_the_first_review_ever_does_not_catch_up_a_fortnight(tmp_path, archive_root):
    out = ReviewTopEdition(_db(), MONDAY, tmp_path / "charts").build()   # no previous review
    assert out.subject.endswith("3 results") and "Sat 29" not in out.html


def test_the_reckoning_names_the_case_and_the_movement(tmp_path, archive_root):
    _write_claims(archive_root)
    out = _build(tmp_path)
    text = out.text
    assert "Alpha 4–0 Beta." in text
    assert "Friday's case: top-three clash." in text
    assert "Alpha up from 2nd to 1st" in text and "Beta down from 1st to 3rd" in text
    assert config.archive_url("preview", FRIDAY.isoformat()) in out.html


def test_a_pick_dated_after_the_window_waits_for_the_next_review(tmp_path, archive_root):
    _write_claims(archive_root, claims=[{
        "fixture": {"tier": 1, "home_id": "b-fc", "away_id": "c-fc", "home_name": "Beta",
                    "away_name": "Gamma", "date": "2026-09-08", "division_name": "Premier League"},
        "speed": "medium", "score": 9.0, "reasons": [["neighbours"]], "snapshot": {}}])
    out = _build(tmp_path)
    assert "Beta v Gamma" not in out.text and "Friday's picks" not in out.html


def test_a_pick_with_no_result_is_said_so(tmp_path, archive_root):
    _write_claims(archive_root, claims=[{
        "fixture": {"tier": 1, "home_id": "b-fc", "away_id": "c-fc", "home_name": "Beta",
                    "away_name": "Gamma", "date": "2026-09-06", "division_name": "Premier League"},
        "speed": "medium", "score": 9.0, "reasons": [["neighbours"]], "snapshot": {}}])
    out = _build(tmp_path)
    assert "Beta v Gamma: no result on file. Friday's case: neighbours." in out.text


def test_results_that_moved_history_get_prose_and_a_chart(tmp_path, archive_root):
    out = _build(tmp_path)
    assert "Results that moved history" in out.html
    # the HTML escapes the apostrophe; the text version carries the sentence as written
    assert "Alpha FC's 4-0 over Beta United was their biggest win in their record." in out.text
    assert out.images and out.images[0][1] == "chart-0"
    # and the grid row carries the short form
    assert "biggest win on record" in out.html


def test_movement_arrows_come_from_the_preview_snapshot(tmp_path, archive_root):
    without = _build(tmp_path)
    assert "↑" not in without.html and "↓" not in without.html
    _write_claims(archive_root)
    with_snapshot = _build(tmp_path)
    assert "↑1" in with_snapshot.html and "↓2" in with_snapshot.html


def test_streak_watch_reports_a_run_near_the_record(tmp_path, archive_root):
    # Alpha: four wins in a row into the weekend; their record is this run.
    out = _build(tmp_path)
    assert "Alpha FC: 4 wins in a row, equalling their record (2026/27)." in out.text


def test_the_alternate_table_rotates_and_sorts(tmp_path, archive_root):
    conn = _db()
    names = review_mod.names_for(conn)
    home = review_mod.alternate_table(conn, 2027, 1, "home", names)
    assert home[0]["name"] == "Alpha FC" and home[0]["played"] == 3 and home[0]["points"] == 9
    form = review_mod.alternate_table(conn, 2027, 1, "form", names)
    assert form[0]["name"] == "Alpha FC" and form[0]["played"] == 4
    kinds = {review_mod.ALT_TABLES[datetime.date(2026, 9, d).isocalendar()[1] % 3]
             for d in (7, 14, 21)}
    assert len(kinds) == 3


def test_lower_review_covers_other_tiers_and_is_thin_here(tmp_path, archive_root):
    out = _build(tmp_path, ReviewLowerEdition, MONDAY + datetime.timedelta(days=1))
    assert out.thin and "nothing on file" in out.subject
    assert "League One</h2>" not in out.html   # no standings rows in those tiers, so no section


def test_phrasing_covers_every_band_kind():
    names = {"x-fc": "X", "y-fc": "Y"}
    cases = [
        ({"kind": "margin", "band": "notable", "since": 2010, "club_id": "x-fc",
          "detail": {"direction": "defeat", "score": "0-5", "opp_id": "y-fc"}},
         "X's 0-5 defeat by Y was their heaviest since 2009/10.", "heaviest defeat since 2009/10"),
        ({"kind": "opponent", "band": "historic", "since": None, "club_id": "x-fc",
          "detail": {"opp_id": "y-fc", "meetings_before": 6}},
         "X beat Y for the first time on record, at the 7th attempt.", "first win v Y on record"),
        ({"kind": "streak", "band": "notable", "since": 2016, "club_id": "x-fc",
          "detail": {"streak_type": "winless", "length": 12}},
         "X have 12 games without a win in a row, their longest run since 2015/16.",
         "12 games without a win, longest since 2015/16"),
        ({"kind": "start", "band": "of_note", "since": 2019, "club_id": "x-fc",
          "detail": {"direction": "worst", "games": 6, "points": 2}},
         "X have 2 points from 6 games, their worst start since 2018/19.", "worst start since 2018/19"),
    ]
    for band, sentence, tag in cases:
        assert phrasing.band_sentence(band, names) == sentence
        assert phrasing.band_tag(band, names) == tag
