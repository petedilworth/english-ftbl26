"""The pyramid file: every club-season, flat, as the Replay and the allocation notice read it."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import pyramid  # noqa: E402
from test_digest import _make_db  # noqa: E402


def _rows(data, season):
    flat, w = data["seasons"][season - data["first"]], data["row"]
    return [flat[i:i + w] for i in range(0, len(flat), w)]


def test_a_row_is_six_numbers_and_two_lookups():
    data = pyramid.assemble(_make_db())
    assert (data["first"], data["last"], data["row"]) == (2022, 2025, 6) == (2022, 2025, len(pyramid.ROW))
    assert len(data["seasons"]) == 4 and all(len(flat) % 6 == 0 for flat in data["seasons"])
    ids = [c[0] for c in data["clubs"]]
    giant = ids.index("giant-fc")
    # 2021/22: Giant FC twentieth in the top flight and relegated.
    row = next(r for r in _rows(data, 2022) if r[0] == giant)
    assert row[1:3] == [1, 20] and data["divisions"][row[3]] == "League One" and row[4] == 20
    assert data["kinds"][row[5]] == "Relegated"
    assert pyramid.history(data, giant) == [(2022, 1, 20, row[3], 20, 4), (2023, 2, 23, row[3], 23, 4),
                                            (2024, 3, 10, row[3], 10, 0), (2025, 3, 8, row[3], 8, 0)]
    assert data["clubs"][giant][1] == "Giant FC" and not data["live"]


def test_each_tier_is_in_rank_order_and_names_follow_the_season():
    conn = _make_db()
    data = pyramid.assemble(conn)
    for season in range(data["first"], data["last"] + 1):
        rows = _rows(data, season)
        assert rows == sorted(rows, key=lambda r: (r[1], r[2]))
    # The registry's era names, each starting where the tier's rows do.
    assert data["bands"]["1"] == [[2022, "Premier League"]]
    assert data["since"] == {"1": 2022, "2": 2023, "3": 2022}
    assert pyramid.band_names({1: 1959, 5: 1980}, 2007)["1"] == [[1959, "First Division"], [1993, "Premier League"]]
    assert pyramid.band_names({5: 1980}, 2007)["5"][0] == [1980, "Alliance Premier League"]


def test_a_tier_of_several_divisions_is_laid_out_on_its_rank_across_the_tier():
    conn = _make_db()
    conn.execute("ALTER TABLE standings ADD COLUMN tier_position INT")
    conn.execute("ALTER TABLE standings ADD COLUMN division_id TEXT")
    conn.execute("INSERT INTO club_master VALUES ('north-fc','North FC',NULL,NULL,6)")
    conn.execute("INSERT INTO club_master VALUES ('south-fc','South FC',NULL,NULL,6)")
    for cid, name, division, tier_rank in (("north-fc", "North FC", "National League North", 2),
                                           ("south-fc", "South FC", "National League South", 1)):
        conn.execute(
            "INSERT INTO standings (season_end_year, tier, division_name, club_id, club_name, position, played,"
            " points, status, tier_position) VALUES (2025, 6, ?, ?, ?, 1, 46, 90, 'Champions', ?)",
            (division, cid, name, tier_rank))
    data = pyramid.assemble(conn)
    sixth = [r for r in _rows(data, 2025) if r[1] == 6]
    names = [data["clubs"][r[0]][1] for r in sixth]
    assert names == ["South FC", "North FC"]                 # by rank across the tier
    assert [r[2] for r in sixth] == [1, 2] and [r[4] for r in sixth] == [1, 1]   # both first in their division
    assert data["bands"]["6"] == [[2025, "National League North & South"]]


def test_a_club_without_a_page_still_moves_but_is_not_linked():
    conn = _make_db()
    data = pyramid.assemble(conn, pages={"giant-fc"})
    assert [c[0] for c in data["clubs"]].count(None) == 1 and "Steady FC" in [c[1] for c in data["clubs"]]
    conn.execute("INSERT INTO standings VALUES (2025, 3, 'League One', NULL, 'Nameless Town', 24, 46, 1, 1, 44,"
                 " 10, 90, -80, 4, 'Relegated', 'test')")
    data = pyramid.assemble(conn)
    nameless = next(c for c in data["clubs"] if c[1] == "Nameless Town")
    assert nameless[0] is None


def test_a_season_in_progress_is_marked_live():
    conn = _make_db()
    conn.execute("INSERT INTO standings VALUES (2026, 3, 'League One', 'giant-fc', 'Giant FC', 1, 3, 3, 0, 0,"
                 " 6, 0, 6, 9, 'In progress', 'test')")
    data = pyramid.assemble(conn)
    assert data["live"] and data["last"] == 2026
    assert data["kinds"][_rows(data, 2026)[0][5]] == "In progress"


def test_an_empty_database_makes_no_file():
    conn = sqlite3.connect(":memory:")
    assert pyramid.assemble(conn) is None
    conn.execute("CREATE TABLE standings (season_end_year INT, tier INT, division_name TEXT, club_id TEXT,"
                 " club_name TEXT, position INT, status TEXT)")
    conn.execute("CREATE TABLE club_master (club_id TEXT, canonical_name TEXT)")
    assert pyramid.assemble(conn) is None
