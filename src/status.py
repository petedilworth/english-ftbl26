"""
Assign promotion/relegation status to each row in a standings DataFrame.

All cutoff rules live in RULES — edit here to adjust for any season range.
Keys: (tier, season_end_year_from, season_end_year_to_inclusive)
Positions are 1-based and inclusive.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# All position ranges verified against Wikipedia season pages, including the
# 1995 restructure (PL 22→20 clubs, Third Division 22→24) and COVID seasons.
# fmt: off
RULES: dict[tuple[int, int, int], dict] = {
    # ── Tier 1: Premier League ──────────────────────────────────────────────
    # 1993/94: 22 clubs, bottom 3 relegated
    (1, 1994, 1994): {
        "total_clubs":      22,
        "auto_promote":     (),
        "playoff_promote":  (),
        "playoff_relegate": (),
        "auto_relegate":    (20, 22),
    },
    # 1994/95: 22 clubs, FOUR relegated to shrink the league to 20
    (1, 1995, 1995): {
        "total_clubs":      22,
        "auto_promote":     (),
        "playoff_promote":  (),
        "playoff_relegate": (),
        "auto_relegate":    (19, 22),
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
    (2, 1994, 1994): {
        "total_clubs":      24,
        "auto_promote":     (2, 2),    # pos 1 = Champions (also promoted)
        "playoff_promote":  (3, 6),
        "playoff_relegate": (),
        "auto_relegate":    (22, 24),
    },
    # 1994/95: PL contraction — champion only auto; play-offs 2–5; 4 down
    (2, 1995, 1995): {
        "total_clubs":      24,
        "auto_promote":     (),
        "playoff_promote":  (2, 5),
        "playoff_relegate": (),
        "auto_relegate":    (21, 24),
    },
    (2, 1996, 2099): {
        "total_clubs":      24,
        "auto_promote":     (2, 2),
        "playoff_promote":  (3, 6),
        "playoff_relegate": (),
        "auto_relegate":    (22, 24),
    },

    # ── Tier 3: Second Division / League One ────────────────────────────────
    (3, 1994, 1994): {
        "total_clubs":      24,
        "auto_promote":     (2, 2),
        "playoff_promote":  (3, 6),
        "playoff_relegate": (),
        "auto_relegate":    (21, 24),
    },
    # 1994/95: restructure cascade — champion only auto; play-offs 2–5; 5 down
    (3, 1995, 1995): {
        "total_clubs":      24,
        "auto_promote":     (),
        "playoff_promote":  (2, 5),
        "playoff_relegate": (),
        "auto_relegate":    (20, 24),
    },
    (3, 1996, 2099): {
        "total_clubs":      24,
        "auto_promote":     (2, 2),
        "playoff_promote":  (3, 6),
        "playoff_relegate": (),
        "auto_relegate":    (21, 24),
    },
    # 2019/20 COVID: Bury expelled (23 clubs), 3 relegated not 4
    (3, 2020, 2020): {
        "total_clubs":      23,
        "auto_promote":     (2, 2),
        "playoff_promote":  (3, 6),
        "playoff_relegate": (),
        "auto_relegate":    (21, 23),
    },

    # ── Tier 4: Third Division / League Two ─────────────────────────────────
    # 1993/94: 22 clubs, top 3 auto + play-offs 4–7; 0 relegated
    # (Conference champions Kidderminster denied on ground grading)
    (4, 1994, 1994): {
        "total_clubs":      22,
        "auto_promote":     (2, 3),
        "playoff_promote":  (4, 7),
        "playoff_relegate": (),
        "auto_relegate":    (),
    },
    # 1994/95: 22 clubs, top 2 auto + play-offs 3–6; 0 relegated
    # (Conference champions Macclesfield denied on ground grading)
    (4, 1995, 1995): {
        "total_clubs":      22,
        "auto_promote":     (2, 2),
        "playoff_promote":  (3, 6),
        "playoff_relegate": (),
        "auto_relegate":    (),
    },
    # 1995/96: 24 clubs; 0 relegated (Stevenage denied; Torquay reprieved)
    (4, 1996, 1996): {
        "total_clubs":      24,
        "auto_promote":     (2, 3),
        "playoff_promote":  (4, 7),
        "playoff_relegate": (),
        "auto_relegate":    (),
    },
    # 1996/97–2001/02: 1 relegated to the Conference
    (4, 1997, 2002): {
        "total_clubs":      24,
        "auto_promote":     (2, 3),
        "playoff_promote":  (4, 7),
        "playoff_relegate": (),
        "auto_relegate":    (24, 24),
    },
    # 2002/03 onward: 2 relegated
    (4, 2003, 2099): {
        "total_clubs":      24,
        "auto_promote":     (2, 3),
        "playoff_promote":  (4, 7),
        "playoff_relegate": (),
        "auto_relegate":    (23, 24),
    },
    # 2019/20 COVID: only Macclesfield relegated (Stevenage reprieved)
    (4, 2020, 2020): {
        "total_clubs":      24,
        "auto_promote":     (2, 3),
        "playoff_promote":  (4, 7),
        "playoff_relegate": (),
        "auto_relegate":    (24, 24),
    },

    # ── Tier 5: Conference / National League ────────────────────────────────
    # (data starts 2005/06) 2005/06: 22 clubs, play-offs 2–5, 3 relegated
    (5, 2006, 2006): {
        "total_clubs":      22,
        "auto_promote":     (),        # position 1 = Champions handles it
        "playoff_promote":  (2, 5),
        "playoff_relegate": (),
        "auto_relegate":    (20, 22),
    },
    # 2006/07–2016/17: 24 clubs, play-offs 2–5, 4 relegated
    (5, 2007, 2017): {
        "total_clubs":      24,
        "auto_promote":     (),
        "playoff_promote":  (2, 5),
        "playoff_relegate": (),
        "auto_relegate":    (21, 24),
    },
    # 2017/18 onward: play-offs expanded to positions 2–7
    (5, 2018, 2099): {
        "total_clubs":      24,
        "auto_promote":     (),
        "playoff_promote":  (2, 7),
        "playoff_relegate": (),
        "auto_relegate":    (21, 24),
    },
    # 2019/20 COVID (curtailed, PPG): 3 relegated not 4
    (5, 2020, 2020): {
        "total_clubs":      24,
        "auto_promote":     (),
        "playoff_promote":  (2, 7),
        "playoff_relegate": (),
        "auto_relegate":    (22, 24),
    },
    # 2020/21: 23 clubs (Macclesfield expelled), 0 relegated (Tier 6 voided)
    (5, 2021, 2021): {
        "total_clubs":      23,
        "auto_promote":     (),
        "playoff_promote":  (2, 7),
        "playoff_relegate": (),
        "auto_relegate":    (),
    },
    # 2021/22: 23 clubs, 3 relegated
    (5, 2022, 2022): {
        "total_clubs":      23,
        "auto_promote":     (),
        "playoff_promote":  (2, 7),
        "playoff_relegate": (),
        "auto_relegate":    (21, 23),
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
