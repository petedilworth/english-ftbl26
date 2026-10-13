"""This week on the home page: the recipes, the pick, and the hero."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import storylines as st  # noqa: E402

SEASON = 2027


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE standings (season_end_year INT, tier INT, division_name TEXT, club_id TEXT,"
                 " club_name TEXT, position INT, played INT, won INT, drawn INT, lost INT, gd INT, points INT,"
                 " status TEXT, points_deducted INT)")
    conn.execute("CREATE TABLE club_master (club_id TEXT, canonical_name TEXT, color_primary TEXT,"
                 " color_secondary TEXT)")
    conn.execute("CREATE TABLE club_trajectory (club_id TEXT, natural_level_tier INT, natural_level_gap INT)")
    conn.execute("CREATE TABLE club_streak_records (club_id TEXT, streak_type TEXT, record_length INT,"
                 " record_season_end_year INT, current_length INT, current_last_date TEXT)")
    conn.execute("CREATE TABLE matches (season_end_year INT, match_date TEXT, home_club_id TEXT,"
                 " away_club_id TEXT, fthg INT, ftag INT)")
    return conn


def _club(conn, cid, name, tiers: dict[int, int], champion: int | None = None, **now):
    """tiers: season -> tier, with the status read off the next season's tier; `now` overrides this season's row."""
    conn.execute("INSERT INTO club_master VALUES (?,?,?,?)", (cid, name, "#111111", "#eeeeee"))
    for s, t in tiers.items():
        after = tiers.get(s + 1)
        status = ("Champions" if s == champion else "In progress" if s == SEASON else
                  "Promoted" if after is not None and after < t else
                  "Relegated" if after is not None and after > t else "Stayed")
        row = {"position": 10, "played": 8, "won": 3, "drawn": 2, "lost": 3, "gd": 0, "points": 11,
               "status": status, "deducted": 0}
        if s == SEASON:
            row.update(now)
        conn.execute("INSERT INTO standings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (s, t, f"Division {t}", cid, name, row["position"], row["played"], row["won"],
                      row["drawn"], row["lost"], row["gd"], row["points"], row["status"], row["deducted"]))


def test_recipes_write_the_numbers_in_and_pick_keeps_the_most_unusual():
    conn = _db()
    _club(conn, "fox", "Fox FC", {s: 1 for s in range(2016, 2025)} | {2025: 1, 2026: 2, 2027: 3}, champion=2016,
          position=14, played=7, points=9)
    _club(conn, "bounce", "Bounce FC", {2022: 1, 2023: 2, 2024: 1, 2025: 2, 2026: 1, 2027: 2},
          position=24, played=8, points=4)
    _club(conn, "hopeless", "Hopeless FC", {2026: 5, 2027: 5}, position=24, played=12, won=0, drawn=0, lost=12, gd=-20)
    _club(conn, "docked", "Docked FC", {2026: 3, 2027: 3}, position=20, points=5, deducted=6)
    _club(conn, "sleeper", "Sleeper FC", {2026: 7, 2027: 7}, position=6)
    for cid in ("a", "b", "c", "d"):
        _club(conn, cid, cid.upper(), {2026: 3, 2027: 3})
    conn.execute("INSERT INTO club_trajectory VALUES ('sleeper', 3, 4)")
    conn.execute("INSERT INTO club_streak_records VALUES ('hopeless', 'loss', 12, 2027, 12, '2026-10-03')")
    conn.execute("INSERT INTO club_streak_records VALUES ('a', 'winless', 25, 2019, 25, '2019-04-01')")  # stale

    cands = st.candidates(conn, SEASON)
    tags = {c["tag"] for c in cands}
    assert {"Yo-yo", "Drop", "Docked", "Level", "Record"} <= tags
    assert all("None" not in c["text"] for c in cands)
    assert not any("A have not won" in c["text"] for c in cands), "a streak that ended in 2019 is not this week"

    lines = st.pick(cands, built={"yo-yo", "the-drop", "safe-thresholds", "points-deductions", "natural-level",
                                  "records"}, exclude="fox")
    assert not any(c["club_id"] == "fox" for c in lines), "the hero's club does not get a line as well"
    assert lines == sorted(lines, key=lambda c: (-c["weight"], c["text"]))
    assert all(c["slug"] != "fallen-giants" for c in lines), "a page that was not built gets no line"
    bounce = next(c for c in lines if c["tag"] == "Yo-yo")
    assert "relegated, promoted, relegated, promoted, relegated" in bounce["text"] and "Five seasons" in bounce["text"]
    docked = next(c for c in lines if c["tag"] == "Docked")
    assert "6 points" in docked["text"] and "would be" in docked["text"]
    sleeper = next(c for c in lines if c["tag"] == "Level")
    assert "four divisions below" in sleeper["text"]


def test_pick_limits_each_tag_and_each_club():
    cands = [st._line("Drop", f"club {i} text", "x", "p", 10 - i, f"c{i % 3}", "the-drop") for i in range(6)]
    cands.append(st._line("Luck", "two clubs", "x", "p", 1, None, "luck"))
    lines = st.pick(cands, limit=8, per_tag=2)
    assert [c["text"] for c in lines] == ["club 0 text", "club 1 text", "two clubs"]


def test_the_hero_is_a_champion_now_in_the_third_tier():
    conn = _db()
    _club(conn, "fox", "Fox FC", {s: 1 for s in range(2016, 2025)} | {2025: 1, 2026: 2, 2027: 3}, champion=2016,
          position=14, played=7, points=9)
    _club(conn, "other", "Other FC", {2026: 3, 2027: 3})
    conn.executemany("INSERT INTO matches VALUES (2027, ?, 'fox', 'other', ?, ?)",
                     [("2026-09-01", 2, 0), ("2026-09-08", 1, 1), ("2026-09-15", 0, 3)])
    h = st.hero(conn, SEASON)
    assert h["name"] == "Fox FC" and h["past"] == "Champions of England, 2015/16." and h["present"] == "Fourteenth in the Division 3."
    assert h["form"] == "WDL" and h["points"][0] == (2016, 1) and h["points"][-1] == (2027, 3)
    sp = st.sparkline(h["points"], h["first"], h["latest"])
    assert sp["start"][1] < sp["end"][1], "tier 1 sits above tier 3 on the line"


def test_the_hero_falls_back_to_the_longest_serving_giant():
    conn = _db()
    _club(conn, "owl", "Owl FC", {s: 1 for s in range(1990, 2001)} | {2026: 3, 2027: 3}, position=4)
    _club(conn, "other", "Other FC", {2026: 3, 2027: 3})
    h = st.hero(conn, SEASON)
    assert h["name"] == "Owl FC" and h["past"].startswith("Eleven seasons in the top flight, the last 1999/00")
    assert h["present"] == "Fourth in the Division 3."


def test_words_and_ordinals():
    assert st.ordinal(1) == "first" and st.ordinal(24) == "twenty-fourth" and st.ordinal(30) == "30th"
    assert st.word(15) == "fifteen" and st.word(40) == "40"


def test_a_run_that_is_itself_the_record_is_called_one():
    conn = _db()
    _club(conn, "wall", "Wall FC", {2026: 4, 2027: 4}, position=1, played=9, points=27)
    _club(conn, "old", "Old FC", {2026: 4, 2027: 4}, position=5, played=9, points=14)
    for cid in ("a", "b", "c"):
        _club(conn, cid, cid.upper(), {2026: 4, 2027: 4})
    # records.py moves the record onto the live run as it passes the old one: same length, dated this season.
    conn.execute("INSERT INTO club_streak_records VALUES ('wall', 'win', 9, 2027, 9, '2026-10-03')")
    conn.execute("INSERT INTO club_streak_records VALUES ('old', 'unbeaten', 10, 2015, 9, '2026-10-03')")
    lines = {c["club_id"]: c["text"] for c in st.record_lines(conn, SEASON, st._table(conn, SEASON))}
    assert lines["wall"].startswith("Wall FC have won <b>9</b> in a row, a club record.")
    assert lines["old"].startswith("Old FC are unbeaten in <b>9</b>, one short of the club record set in 2014/15.")


def test_the_giants_line_names_climbers_from_one_division_and_escapes_names():
    conn = _db()
    # Two former top-flight clubs climbing in different third-tier divisions, one sinking.
    _club(conn, "ab", "A &amp; B FC".replace("&amp;", "&"), {2000: 1, 2026: 3, 2027: 3}, position=1, played=9)
    _club(conn, "cd", "CD FC", {2001: 1, 2026: 3, 2027: 3}, position=2, played=9)
    _club(conn, "ef", "EF FC", {2002: 1, 2026: 3, 2027: 3}, position=23, played=9)
    for i, cid in enumerate(("p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z", "aa", "bb", "cc", "dd",
                             "ee", "ff", "gg", "hh", "ii", "jj")):
        _club(conn, cid, cid.upper(), {2026: 3, 2027: 3}, position=3 + i, played=9)
    conn.execute("UPDATE standings SET division_name = 'Division 3 South' WHERE club_id = 'cd' AND season_end_year = 2027")
    line = st.giants_lines(conn, SEASON, st._table(conn, SEASON))[0]
    assert "A &amp; B FC is in the top quarter of the Division 3." in line["text"]
    assert "CD FC" not in line["text"], "a climber in another division is not in this division's top quarter"
    assert "EF FC are <b>twenty-third of 23</b>" in line["text"] and line["club_id"] == "ef"


def test_lost_the_lot_says_bottom_only_when_bottom():
    conn = _db()
    _club(conn, "worse", "Worse FC", {2026: 5, 2027: 5}, position=6, played=6, won=0, drawn=0, lost=6, gd=-9, points=0)
    _club(conn, "worst", "Worst FC", {2026: 5, 2027: 5}, position=7, played=6, won=0, drawn=0, lost=6, gd=-12, points=0)
    for i, cid in enumerate(("a", "b", "c", "d", "e")):
        _club(conn, cid, cid.upper(), {2026: 5, 2027: 5}, position=1 + i)
    lines = {c["club_id"]: c["text"] for c in st.bottom_lines(conn, SEASON, st._table(conn, SEASON))}
    assert "Bottom of the Division 5." in lines["worst"] and "Sixth of 7 in the Division 5." in lines["worse"]
