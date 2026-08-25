import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import crosscheck


def _db(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE standings (season_end_year INT, tier INT, club_name TEXT,"
        " points INT, gd INT, played INT, status TEXT, points_deducted INT,"
        " data_complete INT)"
    )
    conn.executemany(
        "INSERT INTO standings VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return conn


def _reference(tmp_path, rows):
    path = tmp_path / "ref.csv"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["season", "tier", "team_name", "played", "points",
                    "goal_difference", "point_adjustment"])
        for r in rows:
            w.writerow(r)
    return path


def test_agreement_is_silent(tmp_path):
    conn = _db([(1994, 1, "A", 80, 20, 42, "Stayed", 0, 1),
                (1994, 1, "B", 70, 10, 42, "Stayed", 0, 1)])
    ref = _reference(tmp_path, [[1993, 1, "A", 42, 80, 20, 0],
                                [1993, 1, "B", 42, 70, 10, 0]])
    assert crosscheck.compare(conn, ref) == []


def test_a_differing_scoreline_is_reported(tmp_path):
    conn = _db([(1994, 1, "A", 80, 20, 42, "Stayed", 0, 1),
                (1994, 1, "B", 70, 10, 42, "Stayed", 0, 1)])
    ref = _reference(tmp_path, [[1993, 1, "A", 42, 83, 26, 0],
                                [1993, 1, "B", 42, 67, 4, 0]])
    found = crosscheck.compare(conn, ref)
    assert len(found) == 1
    assert found[0]["clubs"] == 2
    assert found[0]["season_end_year"] == 1994


def test_club_names_and_tie_order_do_not_matter(tmp_path):
    # Sources disagree on naming ("Hull" vs "Hull City") and on how they
    # order clubs level on points, so neither can be part of the comparison.
    conn = _db([(1994, 1, "Hull", 70, 10, 42, "Stayed", 0, 1),
                (1994, 1, "Bristol Rvs", 70, 10, 42, "Stayed", 0, 1)])
    ref = _reference(tmp_path, [[1993, 1, "Bristol Rovers", 42, 70, 10, 0],
                                [1993, 1, "Hull City", 42, 70, 10, 0]])
    assert crosscheck.compare(conn, ref) == []


def test_deductions_are_added_back_before_comparing(tmp_path):
    # We store the table after the sanction; the reference stores it before,
    # with the adjustment in its own column. Comparing raw totals would flag
    # every sanctioned club-season as an error.
    conn = _db([(2010, 1, "Portsmouth", 19, -32, 38, "Relegated", 9, 1)])
    ref = _reference(tmp_path, [[2009, 1, "Portsmouth", 38, 19, -32, -9]])
    assert crosscheck.compare(conn, ref) == []


def test_incomplete_and_in_progress_tables_are_skipped(tmp_path):
    conn = _db([(2020, 1, "A", 40, 0, 30, "Stayed", 0, 0),
                (2027, 1, "B", 3, 1, 1, "In progress", 0, 1)])
    ref = _reference(tmp_path, [[2019, 1, "A", 38, 90, 40, 0],
                                [2026, 1, "B", 38, 90, 40, 0]])
    assert crosscheck.compare(conn, ref) == []


def test_expunged_reference_rows_are_ignored(tmp_path):
    # Clubs whose record was struck out survive in the reference as a
    # nil-played row; they belong in no comparison of what was played.
    conn = _db([(1992, 4, "A", 80, 20, 42, "Stayed", 0, 1)])
    ref = _reference(tmp_path, [[1991, 4, "A", 42, 80, 20, 0],
                                [1991, 4, "Aldershot", 0, 0, 0, 0]])
    assert crosscheck.compare(conn, ref) == []
