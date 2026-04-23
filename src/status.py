"""
Assign promotion/relegation status to each row in a standings DataFrame.

All cutoff rules live in RULES — edit here to adjust for any season range.
Keys: (tier, season_end_year_from, season_end_year_to_inclusive)
Positions are 1-based and inclusive.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# fmt: off
RULES: dict[tuple[int, int, int], dict] = {
    # ── Tier 1: Premier League ──────────────────────────────────────────────
    # 1993/94 and 1994/95: 22 clubs; 4 relegated as part of PL contraction
    (1, 1994, 1995): {
        "total_clubs":      22,
        "auto_promote":     (),
        "playoff_promote":  (),
        "playoff_relegate": (),
        "auto_relegate":    (20, 22),
    },
    # 1995/96 onward: 20 clubs, bottom 3 relegated
    (1, 1996, 2099): {
        "total_clubs":      20,
        "auto_promote":     (),
        "playoff_promote":  (),
        "playoff_relegate": (),
        "auto_relegate":    (18, 20),
    },

    # ── Tier 2: First Division / Championship ───────────────────────────────
    # Top 2 auto-promoted; positions 3–6 play off; bottom 3 relegated
    (2, 1994, 2099): {
        "total_clubs":      24,
        "auto_promote":     (2, 2),    # positions 2..2 (pos 1 = Champions = auto-promoted)
        "playoff_promote":  (3, 6),
        "playoff_relegate": (),
        "auto_relegate":    (22, 24),
    },

    # ── Tier 3: Second Division / League One ────────────────────────────────
    # Top 2 auto-promoted; positions 3–7 play off; bottom 4 relegated
    (3, 1994, 2099): {
        "total_clubs":      24,
        "auto_promote":     (2, 2),
        "playoff_promote":  (3, 7),
        "playoff_relegate": (),
        "auto_relegate":    (21, 24),
    },

    # ── Tier 4: Third Division / League Two ─────────────────────────────────
    # Same structure as Tier 3
    (4, 1994, 2099): {
        "total_clubs":      24,
        "auto_promote":     (2, 2),
        "playoff_promote":  (3, 7),
        "playoff_relegate": (),
        "auto_relegate":    (21, 24),
    },

    # ── Tier 5: National League (Conference) ────────────────────────────────
    # 1 auto-promoted; positions 2–3 play off; bottom 3 relegated to Tier 6
    (5, 2006, 2099): {
        "total_clubs":      24,
        "auto_promote":     (),        # position 1 = Champions handles it
        "playoff_promote":  (2, 3),
        "playoff_relegate": (),
        "auto_relegate":    (22, 24),
    },
}
# fmt: on


def get_rules(tier: int, season_end_year: int) -> dict:
    """
    Return the most recently applicable rule for (tier, season_end_year).
    Raises KeyError if no matching rule exists.
    """
    candidates = [
        (from_yr, rule)
        for (t, from_yr, to_yr), rule in RULES.items()
        if t == tier and from_yr <= season_end_year <= to_yr
    ]
    if not candidates:
        raise KeyError(
            f"No promotion/relegation rules defined for tier={tier}, season={season_end_year}"
        )
    # Pick the rule with the highest from_year (most specific / most recent)
    _, rule = max(candidates, key=lambda x: x[0])
    return rule


def assign_status(
    standings: pd.DataFrame,
    season_end_year: int,
    tier: int,
) -> pd.DataFrame:
    """
    Add a 'status' column to the standings DataFrame.
    Expects a 'position' column (1-based integers).
    """
    try:
        rules = get_rules(tier, season_end_year)
    except KeyError as exc:
        logger.warning("%s — defaulting all rows to 'Stayed'", exc)
        standings = standings.copy()
        standings["status"] = "Stayed"
        return standings

    actual_clubs = len(standings)
    expected_clubs = rules["total_clubs"]
    if actual_clubs != expected_clubs:
        logger.warning(
            "Tier %d %d: expected %d clubs but found %d — applying rules to available positions",
            tier,
            season_end_year,
            expected_clubs,
            actual_clubs,
        )

    auto_promote_range  = _to_positions(rules["auto_promote"])
    playoff_promote_range = _to_positions(rules["playoff_promote"])
    auto_relegate_range = _to_positions(rules["auto_relegate"])
    playoff_relegate_range = _to_positions(rules["playoff_relegate"])

    standings = standings.copy()

    def _classify(pos: int) -> str:
        if pos == 1:
            return "Champions"
        if pos in auto_promote_range:
            return "Promoted"
        if pos in playoff_promote_range:
            return "Play-off Promoted"
        if pos in auto_relegate_range:
            return "Relegated"
        if pos in playoff_relegate_range:
            return "Play-off Relegated"
        return "Stayed"

    standings["status"] = standings["position"].apply(_classify)
    return standings


def _to_positions(range_tuple: tuple) -> frozenset[int]:
    """Convert an inclusive (lo, hi) tuple to a frozenset of ints. Empty tuple → empty set."""
    if not range_tuple:
        return frozenset()
    lo, hi = range_tuple
    return frozenset(range(lo, hi + 1))
