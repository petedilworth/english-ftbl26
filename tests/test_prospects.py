import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import catchment
import prospects


def _db(clubs, standings, catchment_rows=(), deductions=()):
    """clubs: (club_id, name, current_tier, lineage_parent_id)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_master (club_id TEXT, canonical_name TEXT,"
                 " current_tier INT, lineage_parent_id TEXT)")
    conn.execute("CREATE TABLE standings (club_id TEXT, tier INT,"
                 " season_end_year INT)")
    conn.execute("CREATE TABLE points_deductions (club_id TEXT, applied INT)")
    conn.execute(catchment.CREATE_CLUB_CATCHMENT_SQL)
    conn.executemany("INSERT INTO club_master VALUES (?,?,?,?)", clubs)
    conn.executemany("INSERT INTO standings VALUES (?,?,?)", standings)
    conn.executemany("INSERT INTO points_deductions VALUES (?,?)", deductions)
    conn.executemany(
        "INSERT INTO club_catchment (club_id, catchment_pop_restored,"
        " catchment_income, contest_ratio, model_version) VALUES (?,?,?,?,'test')",
        catchment_rows)
    conn.commit()
    return conn


FALLEN = [
    ("alpha-fc", "Alpha", 6, None),      # tier-3 ceiling, still trading
    ("beta-fc", "Beta", 0, None),        # tier-3 ceiling, wound up
    ("gamma-fc", "Gamma", 6, None),      # tier-5 ceiling
]
SEASONS = [
    ("alpha-fc", 3, 2010), ("alpha-fc", 5, 2025),
    ("beta-fc", 3, 2008), ("beta-fc", 5, 2024),
    ("gamma-fc", 5, 2023), ("gamma-fc", 5, 2025),
]


def test_bands_separate_the_three_kinds_of_bet():
    rows = {r["club_id"]: r for r in prospects.candidates(_db(FALLEN, SEASONS))}
    assert rows["alpha-fc"]["band"] == "A"
    assert rows["beta-fc"]["band"] == "B"
    assert rows["gamma-fc"]["band"] == "C"


def test_a_club_still_in_the_league_is_not_a_candidate():
    conn = _db(FALLEN + [("live-fc", "Live", 4, None)],
               SEASONS + [("live-fc", 3, 2025)])
    assert "live-fc" not in {r["club_id"] for r in prospects.candidates(conn)}


def test_an_unknown_input_is_not_scored_as_a_zero():
    """
    The failure mode this guards: a club nobody has researched sinking to
    the bottom as though it had been researched and failed.
    """
    conn = _db(FALLEN, SEASONS, catchment_rows=[
        ("alpha-fc", 500_000, 30_000, 0.2),
        ("beta-fc", 500_000, 30_000, 0.2),
        ("gamma-fc", 500_000, 30_000, 0.2),
    ])
    rows = {r["club_id"]: r for r in prospects.score(prospects.candidates(conn))}
    alpha = rows["alpha-fc"]
    assert alpha["tenure"] == "unknown"
    assert "tenure" in alpha["missing"]
    # Scored on the inputs that exist, so still a real number.
    assert alpha["score"] is not None and alpha["score"] > 0
    assert "tenure" not in alpha["parts"]


def test_a_club_with_a_successor_is_excluded_not_ranked():
    conn = _db(FALLEN + [("old-fc", "Old", 0, None),
                         ("new-fc", "New", 5, "old-fc")],
               SEASONS + [("old-fc", 2, 2015), ("new-fc", 5, 2025)])
    result = prospects.screen(conn)
    excluded = {r["club_id"]: r["excluded"] for r in result["excluded"]}
    assert "old-fc" in excluded
    assert "new-fc" in excluded["old-fc"]
    ranked = {r["club_id"] for band in result["bands"].values() for r in band}
    assert "old-fc" not in ranked


def test_a_long_absence_is_excluded_with_the_reason_stated():
    conn = _db(FALLEN + [("gone-fc", "Gone", 0, None)],
               SEASONS + [("gone-fc", 3, 1975)])
    result = prospects.screen(conn)
    reasons = {r["club_id"]: r["excluded"] for r in result["excluded"]}
    assert "gone-fc" in reasons
    assert "absent" in reasons["gone-fc"]


def test_no_catchment_data_means_no_ranking_is_claimed():
    """
    Ceiling and fall alone would rank on nostalgia. The screen must say it
    cannot answer rather than answering with the free half of the thesis.
    """
    result = prospects.screen(_db(FALLEN, SEASONS))
    assert result["blocked"]
    assert "catchment" in result["blocked"]
    assert "NOT RANKED" in prospects.render(result)


def test_catchment_data_unblocks_the_ranking():
    conn = _db(FALLEN, SEASONS, catchment_rows=[
        ("alpha-fc", 900_000, 34_000, 0.10),
        ("beta-fc", 120_000, 26_000, 0.80),
        ("gamma-fc", 400_000, 30_000, 0.40),
    ])
    result = prospects.screen(conn)
    assert result["blocked"] is None
    band_a = result["bands"]["A"]
    assert band_a and band_a[0]["score"] is not None


def test_a_bigger_uncontested_catchment_outranks_a_contested_one():
    conn = _db(
        [("big-fc", "Big", 6, None), ("small-fc", "Small", 6, None)],
        [("big-fc", 3, 2024), ("small-fc", 3, 2024)],
        catchment_rows=[("big-fc", 900_000, 30_000, 0.05),
                        ("small-fc", 90_000, 30_000, 0.90)],
    )
    order = [r["club_id"] for r in prospects.screen(conn)["bands"]["A"]]
    assert order[0] == "big-fc"


def test_normalise_leaves_missing_values_out_rather_than_at_zero():
    got = prospects._normalise({"a": 10, "b": 20, "c": None})
    assert set(got) == {"a", "b"}
    assert got["a"] == 0.0 and got["b"] == 1.0


def test_normalise_inverts_when_lower_is_better():
    got = prospects._normalise({"a": 10, "b": 20}, invert=True)
    assert got["a"] == 1.0 and got["b"] == 0.0


def test_identical_values_do_not_manufacture_a_ranking():
    got = prospects._normalise({"a": 5, "b": 5})
    assert got == {"a": 0.5, "b": 0.5}
