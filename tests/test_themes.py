"""The theme pages: membership, the minimum, and each table."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from test_digest import _make_db  # noqa: E402

import themes  # noqa: E402

NAMES = {"giant-fc": "Giant FC", "steady-fc": "Steady FC"}


def _db_with_deductions():
    conn = _make_db()
    conn.execute("CREATE TABLE points_deductions (club_id TEXT, season_end_year INT, tier INT,"
                 " points INT, category TEXT, applied INT, reason TEXT, source_url TEXT, note TEXT)")
    conn.execute("INSERT INTO points_deductions VALUES ('giant-fc', 2025, 3, 10, 'administration',"
                 " 1, 'Entered administration', '', 'A long note')")
    conn.execute("INSERT INTO points_deductions VALUES ('steady-fc', 2024, 3, 3, 'ineligible-player',"
                 " 1, 'Fielded an ineligible player', '', '')")
    conn.execute("INSERT INTO points_deductions VALUES ('steady-fc', 2025, 4, 2, 'other',"
                 " 0, 'Suspended', '', '')")
    conn.execute("ALTER TABLE standings ADD COLUMN points_deducted INT DEFAULT 0")
    conn.execute("UPDATE standings SET points_deducted = 10 WHERE club_id='giant-fc' AND season_end_year=2025")
    return conn


def test_deductions_come_from_the_database_and_administration_is_the_union():
    conn = _db_with_deductions()
    story = {"giant-fc": ["points-deductions", "phoenix"],
             "old-fc": ["administration", "points-deductions"]}   # pre-2004: no deduction row
    members = themes.membership(conn, story)
    assert members["points-deductions"] == {"giant-fc", "steady-fc"}   # old-fc's is a CSV gap
    assert members["administration"] == {"giant-fc", "old-fc"}
    assert members["phoenix"] == {"giant-fc"}


def test_the_minimum_keeps_small_themes_off_the_site():
    members = {"big": set(f"c{i}" for i in range(themes.MIN_THEME_CLUBS)),
               "small": {"a", "b", "c"}}
    assert themes.published(members) == {"big"}


def test_deduction_rows_say_where_they_would_have_finished():
    conn = _db_with_deductions()
    columns, rows, dimension = themes.deduction_rows(
        conn, {"giant-fc", "steady-fc"}, {}, NAMES)
    assert columns[-2:] == ["Finished", "Without it"] and dimension == "by points docked"
    by_club = {(r[0]["text"], r[1]["text"]): r for r in rows}
    giant = by_club[("Giant FC", "2024/25")]
    assert giant[3]["text"] == "10" and giant[5]["text"] == "8th"
    # 55 points, 10 restored = 65: above Steady on 55, so 7th... in a two-club
    # division, 1st. The point is that it differs from where they finished.
    assert giant[6]["text"] == "1st"
    suspended = by_club[("Steady FC", "2024/25")]
    assert "(suspended)" in suspended[4]["text"] and suspended[6]["text"] == "—"
    assert rows[0][3]["text"] == "10"   # sorted by points docked


def test_administration_rows_show_before_during_and_after():
    conn = _db_with_deductions()
    facts = {"giant-fc": {"administration": [{"year": 2025, "month": 3, "points_deducted": 10,
                                               "note": "Rent arrears"}]}}
    columns, rows, _ = themes.administration_rows(conn, {"giant-fc"}, facts, NAMES)
    assert columns[3:6] == ["The season before", "That season", "Two seasons on"]
    (row,) = rows
    assert row[0]["text"] == "2024/25" and row[2]["text"] == "10"
    assert row[3]["text"] == "League One, 10th" and row[4]["text"] == "League One, 8th"
    assert row[5]["text"] == "—"                 # 2027 not in this database
    assert row[6]["text"] == "Rent arrears"      # the story's note enriches the database row


def test_phoenix_rows_measure_the_climb():
    conn = _make_db()
    facts = {"giant-fc": {"phoenix_of": "Old Giant", "predecessor_folded": 2020, "founded": 2021}}
    columns, rows, _ = themes.phoenix_rows(conn, {"giant-fc"}, facts, NAMES)
    (row,) = rows
    assert [c["text"] for c in row[1:4]] == ["Old Giant", "2020", "2021"]
    assert row[4]["text"] == "2021/22, League One"    # first season after founding
    assert row[5]["text"] == "League One, 2021/22"    # tier 1 in 2022 is before 'founded'? no: >2021
    assert row[6]["text"] == "1"


def test_fan_owned_rows_cover_spells_that_ended_and_ones_that_did_not():
    conn = _make_db()
    facts = {"giant-fc": {"fan_owned": [{"trust": "Giant Trust", "from": 2021, "to": 2024}]},
             "steady-fc": {"ownership_model": "fan_trust", "owner": "Steady Trust", "owner_since": 2022}}
    columns, rows, _ = themes.fan_owned_rows(conn, {"giant-fc", "steady-fc"}, facts, NAMES)
    assert [r[0]["text"] for r in rows] == ["Giant FC", "Steady FC"]   # oldest first
    giant, steady = rows
    assert giant[3]["text"] == "2024" and giant[5]["text"] == "League One, 10th"
    assert steady[3]["text"] == "now" and steady[5]["text"] == "League One, 7th"
