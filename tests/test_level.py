import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import level

from level import (
    MIN_RECORDED,
    MIN_WINDOW,
    OUTSIDE,
    classify,
    distribution,
    level_gap,
    natural_level,
    primary_tier,
    the,
    trend,
    window_buckets,
)


# ── The window ─────────────────────────────────────────────────────────
# The standings table only records a club while it is inside Tiers 1-5, so
# counting recorded seasons alone silently ignores every season a club
# spent below the pyramid. These pin the fix.

def test_absent_seasons_enter_the_window():
    # Altrincham's real shape: National League, dropped out twice, came back.
    tiers = {}
    for y in range(2006, 2012): tiers[y] = 5
    for y in range(2015, 2017): tiers[y] = 5
    for y in range(2021, 2027): tiers[y] = 5
    nl = natural_level(tiers)

    assert nl.seasons == 21          # 2006-2026 inclusive, not the 14 recorded
    assert nl.recorded == 14
    assert nl.distribution["outside"] == 7
    # The regression this whole module exists to prevent
    assert "ever-present" not in nl.label


def test_window_runs_first_to_last_recorded_season():
    assert window_buckets({2000: 3, 2003: 4}) == [3, OUTSIDE, OUTSIDE, 4]


def test_window_never_starts_or_ends_outside():
    # Both endpoints are recorded by construction, so a club can never be
    # classified as "ever-present" in the outside bucket.
    for tiers in ({2000: 2, 2010: 5}, {1994: 1, 2026: 4}, {2005: 3}):
        b = window_buckets(tiers)
        assert b[0] != OUTSIDE and b[-1] != OUTSIDE


def test_empty_history_is_handled():
    assert window_buckets({}) == []
    assert natural_level({}).kind == "insufficient"


# ── Primary tier ───────────────────────────────────────────────────────

def test_median_low_breaks_ties_to_the_higher_division():
    # An even split between two divisions resolves to the better one
    # rather than to a fractional tier that rounds arbitrarily.
    assert primary_tier([2, 2, 3, 3]) == 2
    assert primary_tier([1, 1, 4, 4]) == 1


# ── Classification ─────────────────────────────────────────────────────

def test_classify_cases():
    cases = [
        # (buckets, expected kind, expected tier)
        ([1] * 20,                              "ever-present", 1),
        ([2] * 16 + [3] * 4,                    "established",  2),
        ([1] * 12 + [2] * 11,                   "yo-yo",        1),
        # Spread across three divisions, no single one dominant and no
        # adjacent pair reaching the yo-yo threshold
        ([3] * 8 + [2] * 6 + [4] * 6,           "mixed",        3),
    ]
    for buckets, kind, tier in cases:
        got = classify(buckets)
        assert got["kind"] == kind, f"{buckets[:5]}... expected {kind}, got {got['kind']}"
        assert got["tier"] == tier


def test_yo_yo_records_its_partner_division():
    got = classify([1] * 12 + [2] * 11)
    assert got["second_tier"] == 2
    assert "yo-yo" in got["label"]
    # Reads as full division names, in pyramid order
    assert got["label"] == "Premier League / Championship yo-yo club"


def test_established_boundary_is_inclusive():
    # Exactly 60% at the primary tier counts as established
    assert classify([2] * 12 + [3] * 4 + [1] * 4)["kind"] == "established"


def test_single_outlier_season_does_not_trigger_broad():
    # A Championship club with one freak non-league season spans tiers 2-6
    # numerically, but calling that "whole-pyramid range" would be absurd.
    got = classify([2] * 10 + [3] * 6 + [OUTSIDE])
    assert got["kind"] != "broad"


def test_genuine_spread_does_trigger_broad():
    # Luton-shaped: real, repeated time in four or more divisions
    got = classify([1] * 2 + [2] * 6 + [3] * 7 + [4] * 5 + [5] * 4)
    assert got["kind"] == "broad"
    assert "whole-pyramid range" in got["label"]


def test_ever_present_never_lands_on_the_outside_bucket():
    # Guaranteed by the window invariant, but worth pinning explicitly
    for tiers in ({2006: 5, 2010: 5, 2016: 5, 2026: 5}, {2000: 4, 2020: 4}):
        nl = natural_level(tiers)
        assert not (nl.kind == "ever-present" and nl.tier == OUTSIDE)


# ── Thin records ───────────────────────────────────────────────────────

def test_insufficient_thresholds():
    assert classify([3] * (MIN_WINDOW - 1))["kind"] == "insufficient"
    assert classify([3] * MIN_WINDOW)["kind"] != "insufficient"      # inclusive
    # A long window with barely any recorded seasons is still too thin
    thin = [5] + [OUTSIDE] * 18 + [5]
    assert sum(1 for b in thin if b != OUTSIDE) < MIN_RECORDED
    assert classify(thin)["kind"] == "insufficient"


def test_insufficient_record_has_no_tier_or_share():
    got = classify([4] * 3)
    assert got["tier"] is None and got["share"] is None
    assert got["label"] == "Insufficient record"


# ── Coverage: the tier-5 boundary ──────────────────────────────────────

def test_gap_before_tier5_coverage_softens_the_wording():
    # Tier 5 isn't recorded before 1979/80, so a gap then might have been a
    # Conference season we simply cannot see - never call it "non-league".
    nl = natural_level({1972: 4, 1977: 4, 1978: 4, 1979: 4, 1980: 4,
                        1981: 4, 1982: 4, 1983: 4})
    assert nl.coverage_note == "pre-coverage-gap"


def test_a_gap_inside_tier5_coverage_is_not_softened():
    # The boundary used to sit at 2005/06, where football-data.co.uk's files
    # begin, long after the backfill had pushed the data to 1979/80. A club
    # missing from the tables in 1999 was outside the top five tiers, and the
    # page should say so.
    nl = natural_level({1996: 4, 1997: 4, 1998: 4, 2003: 4, 2004: 4,
                        2005: 4, 2006: 4, 2007: 4})
    assert nl.coverage_note is None


def test_modern_gap_is_named_non_league():
    tiers = {y: 5 for y in range(2010, 2016)}
    tiers.update({y: 5 for y in range(2019, 2025)})
    nl = natural_level(tiers)
    assert nl.coverage_note is None


def test_outside_dominant_club_says_mostly():
    tiers = {2010: 5, 2013: 5, 2014: 5, 2020: 5, 2024: 5}
    nl = natural_level(tiers)
    if nl.tier == OUTSIDE:
        assert nl.label.startswith("Mostly")


# ── Trend ──────────────────────────────────────────────────────────────

def test_trend_measures_direction_not_level():
    # A club that fell to non-league and climbed back is RISING, even
    # though its recent seasons still sit below its long-run average.
    # Comparing recent seasons against the whole window gets this backwards.
    fell_then_rose = [2] * 8 + [3] * 4 + [OUTSIDE] * 6 + [5] * 3 + [4, 4, 3, 3, 3]
    assert trend(fell_then_rose)[1] == "rising"


def test_trend_rising_falling_level():
    assert trend([4] * 15 + [2] * 5)[1] == "rising"
    assert trend([2] * 15 + [4] * 5)[1] == "falling"
    assert trend([3] * 20)[1] == "level"


def test_trend_none_for_thin_history():
    assert trend([3] * (MIN_WINDOW - 1)) == (None, None)


# ── Gap ────────────────────────────────────────────────────────────────

def test_level_gap_sign_and_suppression():
    nl = natural_level({y: 2 for y in range(2005, 2026)})
    assert level_gap(nl, 3, is_active=True) == 1      # a division below
    assert level_gap(nl, 1, is_active=True) == -1     # a division above
    assert level_gap(nl, 2, is_active=True) == 0
    # A defunct club's "current tier" is a stale last-recorded tier, so no
    # gap should be reported for it at all.
    assert level_gap(nl, 3, is_active=False) is None


def test_level_gap_none_for_insufficient_record():
    assert level_gap(natural_level({2020: 3, 2021: 3}), 3, is_active=True) is None


# ── Shapes and wording ─────────────────────────────────────────────────

def test_distribution_is_json_ready_and_sums_to_the_window():
    nl = natural_level({2000: 2, 2001: 2, 2003: 3, 2004: 4, 2005: 4,
                        2006: 4, 2007: 4, 2008: 4})
    parsed = json.loads(json.dumps(nl.distribution))
    assert all(isinstance(k, str) for k in parsed)
    assert sum(parsed.values()) == nl.seasons


def test_the_matches_the_sites_existing_division_phrasing():
    assert the(1) == "the Premier League"
    assert the(3) == "League One"          # bare, as digest.narrative does
    assert the(5) == "the National League"


# ── the sentinel and the ladder ────────────────────────────────────────

def test_the_outside_sentinel_cannot_collide_with_a_real_tier():
    """
    OUTSIDE was 6 until tier 6 became a real level of this site. The
    value is persisted in club_trajectory, so a collision would make a
    stored 6 permanently ambiguous between "outside the pyramid" and
    "sixth tier" - unrecoverable, because nothing distinguishes them.
    """
    assert level.OUTSIDE not in level.BUCKET_LADDER[:-1]
    assert level.BUCKET_LADDER[-1] == level.OUTSIDE
    assert level.OUTSIDE > 20, "the sentinel must sort below any real tier"


def test_the_ladder_covers_every_tier_the_database_holds():
    """
    The forcing function for adding a tier. A tier with standings rows but
    no rung is invisible to _spread and _adjacent, and is dropped from the
    distribution bar while still counting in its denominator - so every
    share on that panel would be wrong, quietly.
    """
    import sqlite3
    db = Path(__file__).parent.parent / "data" / "db" / "england.db"
    if not db.exists():
        pytest.skip("no built database")
    tiers = {t for (t,) in sqlite3.connect(db).execute(
        "SELECT DISTINCT tier FROM standings")}
    missing = sorted(tiers - set(level.BUCKET_LADDER))
    assert not missing, f"tiers with no rung on the ladder: {missing}"


def test_every_rung_has_a_name():
    for bucket in level.BUCKET_LADDER:
        if bucket == level.OUTSIDE:
            continue
        assert bucket in level.TIER_NAMES


def test_span_is_measured_in_rungs_not_in_bucket_numbers():
    """
    With the sentinel at 99, arithmetic on the numbers would report a club
    that yo-yos in and out of the League as spanning ninety-nine
    divisions, which clears every "whole-pyramid range" test there is.
    """
    yo_yo = [5, 5, 5, level.OUTSIDE, level.OUTSIDE, 5, level.OUTSIDE]
    assert level._spread(yo_yo) == 2

    top_to_bottom = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert level._spread(top_to_bottom) == 5


def test_the_bottom_tier_and_outside_are_still_neighbours():
    """
    They were adjacent only by the accident of the sentinel being one
    more than the bottom tier. The ladder makes it deliberate, which is
    what keeps "National League / non-league yo-yo" working.
    """
    counts = {5: 6, level.OUTSIDE: 4}
    neighbour, share = level._adjacent(counts, 5, 10)
    assert neighbour == level.OUTSIDE
    assert share == pytest.approx(0.4)


def test_the_top_tier_has_only_one_neighbour():
    counts = {1: 8, 2: 2}
    assert level._adjacent(counts, 1, 10) == (2, pytest.approx(0.2))
