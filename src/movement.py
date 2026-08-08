"""
Promotion and relegation sequences - not lifetime totals (club_trajectory
already carries total_promotions/total_relegations/yo_yo_score for that)
but which seasons were consecutive or close together: back-to-back
relegations, three promotions in a row, a relegation undone and then
repeated a year later.

Reuses the exact promotion/relegation definition already established in
trajectory.py's AGGREGATE_SQL, so this module can never disagree with
total_promotions/total_relegations about what counts as one: a Tier 1
"Champions" is a league title, not a promotion, since there's no tier
above the Premier League to move up into.

A match always requires consecutive season_end_years with no gap, the same
rule trajectory._compute_tier_streaks() uses for tier streaks - a season
missing from the standings table breaks any run through it rather than
silently bridging it.
"""

import sqlite3

PROMOTION_STATUSES = {"Champions", "Promoted", "Play-off Promoted"}
RELEGATION_STATUSES = {"Relegated", "Play-off Relegated"}

RELEGATION_BACK_TO_BACK = "relegation_back_to_back"
RELEGATION_THREE_PLUS = "relegation_three_plus"
RELEGATION_HELD = "relegation_held"
RELEGATION_SANDWICH = "relegation_sandwich"
PROMOTION_BACK_TO_BACK = "promotion_back_to_back"
PROMOTION_THREE_PLUS = "promotion_three_plus"
PROMOTION_PAUSED = "promotion_paused"


def classify(tier: int, status: str) -> str:
    """One season's status -> 'promotion' | 'relegation' | 'stay' | 'other'."""
    if status in PROMOTION_STATUSES and tier != 1:
        return "promotion"
    if status in RELEGATION_STATUSES:
        return "relegation"
    if status == "Stayed" or (status == "Champions" and tier == 1):
        return "stay"
    return "other"


def load_status_histories(
    conn: sqlite3.Connection,
) -> dict[str, list[tuple[int, int, str]]]:
    """{club_id: [(season_end_year, tier, status), ...]} sorted ascending."""
    histories: dict[str, list[tuple[int, int, str]]] = {}
    for club_id, year, tier, status in conn.execute(
        "SELECT club_id, season_end_year, tier, status FROM standings "
        "WHERE club_id IS NOT NULL ORDER BY club_id, season_end_year"
    ):
        histories.setdefault(club_id, []).append((year, tier, status))
    return histories


def _contiguous(a: tuple, b: tuple) -> bool:
    return b[0] - a[0] == 1


def detect_patterns(history: list[tuple[int, int, str]]) -> list[dict]:
    """
    Scan one club's season-ordered (season_end_year, tier, status) history
    for the seven consecutive-movement patterns. Returns
    [{"pattern": <key>, "seasons": [...], "tiers": [...]}, ...] - a club's
    history can produce any number of matches, including none.

    Run-length patterns (back-to-back / three-or-more) and the three-season
    middle-event patterns (held / sandwiched / paused) can never collide on
    the same window: the middle event's classification (stay, promotion or
    relegation) is mutually exclusive, so a given triple of seasons matches
    at most one pattern. The same club can still appear under more than one
    pattern for genuinely different stretches of its history.
    """
    if len(history) < 2:
        return []

    events = [(year, tier, classify(tier, status)) for year, tier, status in history]
    matches: list[dict] = []

    for kind, two_key, three_key in (
        ("relegation", RELEGATION_BACK_TO_BACK, RELEGATION_THREE_PLUS),
        ("promotion", PROMOTION_BACK_TO_BACK, PROMOTION_THREE_PLUS),
    ):
        i = 0
        while i < len(events):
            if events[i][2] != kind:
                i += 1
                continue
            j = i
            while (
                j + 1 < len(events)
                and events[j + 1][2] == kind
                and _contiguous(events[j], events[j + 1])
            ):
                j += 1
            run_length = j - i + 1
            if run_length >= 2:
                run = events[i : j + 1]
                matches.append({
                    "pattern": two_key if run_length == 2 else three_key,
                    "seasons": [e[0] for e in run],
                    "tiers": [e[1] for e in run],
                })
            i = j + 1

    for mid_kind, event_kind, key in (
        ("stay", "relegation", RELEGATION_HELD),
        ("promotion", "relegation", RELEGATION_SANDWICH),
        ("stay", "promotion", PROMOTION_PAUSED),
    ):
        for i in range(len(events) - 2):
            a, b, c = events[i], events[i + 1], events[i + 2]
            if (
                a[2] == event_kind
                and b[2] == mid_kind
                and c[2] == event_kind
                and _contiguous(a, b)
                and _contiguous(b, c)
            ):
                matches.append({
                    "pattern": key,
                    "seasons": [a[0], b[0], c[0]],
                    "tiers": [a[1], b[1], c[1]],
                })

    return matches
