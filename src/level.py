"""
A club's "natural level" — what kind of club this is, as distinct from
where it happens to be sitting this season.

The measure is a distribution, not a single number. Bolton and Sheffield
Wednesday both have a median of Tier 2, but Bolton spent 13 of 33 seasons
in the top flight and Wednesday only 7 — an average hides that, and for a
yo-yo club the average lands on a boundary the club has passed through but
rarely lived at. So we keep the whole per-tier profile and summarise it
into a label.

Two things this module is careful about, because both produce confident
nonsense if ignored:

1. The standings table only records a club in a season when it was inside
   Tiers 1-5. Absence is invisible. Counting only recorded seasons calls
   Altrincham "National League ever-present" when their real shape is
   555555...55....555555 — the gaps are seasons in Tier 6. So the
   denominator is the club's own window (first recorded season to last,
   inclusive), and absent seasons inside it go in an explicit "outside"
   bucket.

2. Tier 5 data only starts in 2006. Before that, a gap means "outside
   Tiers 1-4" and the club may well have been in the Conference — we
   cannot tell. Those clubs are flagged so the wording stays honest and
   never claims "non-league" about a season we simply cannot see.

Scope is the 1993/94-onward era throughout. It says nothing about the
pre-Premier-League game, and the copy should never imply otherwise.
"""

import json
import sqlite3
import statistics
from dataclasses import dataclass

# Tiers 6 and 7 are recorded only for the seasons engsoccerdata covers.
# This does NOT make a gap elsewhere ambiguous: "non-league" means below
# the Football League, and a club missing from the tables in 1999 was
# below it whether or not this project can name the division. The
# coverage note stays about tier 5, where the ambiguity is real.
TIER67_FIRST_SEASON = 2013
TIER67_LAST_SEASON = 2019

# What partial coverage costs, stated because it is not obvious. A club
# that has bounced between the fifth tier and below it now has those
# below-the-line seasons split in two - tier 6 where the data reaches,
# OUTSIDE where it does not - so neither bucket is big enough to earn the
# "National League / non-league yo-yo" label the club plainly deserves.
# Boston United, Dover Athletic, Tamworth and Welling United all lost it
# when tiers 6 and 7 arrived. Extending the coverage closes the gap;
# nothing in this module can.

# Tier 5 (National League) is in the data from 1979/80 onward, so a gap
# before this is "we can't see it", not "they weren't there". It used to be
# 2005/06, which is where football-data.co.uk's files start; the
# engsoccerdata backfill pushed the boundary back twenty-six seasons and
# this constant did not follow it, which left twenty-seven clubs described
# as "outside the recorded divisions" for seasons the data can see
# perfectly well.
TIER5_FIRST_SEASON = 1980

# The bucket for seasons inside a club's window with no standings row.
#
# 99 rather than 6, because tier 6 is a real level of English football and
# a sentinel that collides with one is a sentinel that lies. The value is
# PERSISTED - club_trajectory stores it in natural_level_tier,
# recent_level_tier and natural_level_second_tier - so changing it and
# rebuilding the trajectory table must happen while no tier-6 standings
# row exists. In the other order a stored 6 is permanently ambiguous
# between "outside the pyramid" and "sixth tier", and nothing can tell
# them apart afterwards.
OUTSIDE = 99

# The rungs a club's season can land on, in order, ending with the one
# below the bottom of the recorded pyramid.
#
# Span and adjacency are measured along THIS LIST rather than by
# arithmetic on the numbers, so the sentinel's value stops mattering to
# either. Tier 5 and "outside" are adjacent because they are neighbours on
# the ladder, which is what the code always meant - it used to be true
# only by the accident of the sentinel being 6.
#
# Add 6 and 7 when those tiers gain standings rows. tests/test_level.py
# asserts this covers every tier the database holds, so forgetting is not
# possible.
BUCKET_LADDER = [1, 2, 3, 4, 5, 6, 7, OUTSIDE]

# "Whole-pyramid range" has to mean the same fraction of the pyramid
# however deep the pyramid is recorded. Two thirds of the rungs, rounded
# up, which is the 4 this was written as when the ladder had six.
BROAD_SPREAD = -(-len(BUCKET_LADDER) * 2 // 3)

# Below these, a computed level is noise: one National League cameo would
# otherwise read as a confident "National League club".
MIN_WINDOW = 8
MIN_RECORDED = 4

# Trend compares the club's last few seasons against the stretch before
# them. Comparing recent seasons against the *whole* window instead would
# measure level rather than direction, and gets clubs that fell and then
# recovered exactly backwards — Stockport and Wrexham both climbed out of
# non-league recently, and both come out as "falling" under that test.
RECENT_WINDOW = 5
PRIOR_WINDOW = 10
MIN_PRIOR = 3

TIER_NAMES = {
    1: "Premier League",
    2: "Championship",
    3: "League One",
    4: "League Two",
    5: "National League",
    # Below here a tier is more than one division, so the name is the
    # level rather than a competition anyone enters.
    6: "National League North & South",
    7: "Step 3",
}
OUTSIDE_NAME = "non-league"
OUTSIDE_NAME_AMBIGUOUS = "outside the recorded divisions"


@dataclass(frozen=True)
class NaturalLevel:
    tier: int | None            # 1-6, None when the record is too thin
    second_tier: int | None     # the other half of a yo-yo, else None
    kind: str                   # ever-present|established|yo-yo|broad|mixed|insufficient
    label: str
    share: float | None         # fraction of the window at `tier`
    seasons: int                # window length — the denominator
    recorded: int               # seasons actually in the standings
    distribution: dict[str, int]
    coverage_note: str | None   # None | "pre-coverage-gap"
    recent_tier: int | None
    trend: str | None           # rising|falling|level


def bucket_name(bucket: int, coverage_note: str | None = None) -> str:
    """
    Display name for a bucket. The outside bucket softens its wording when
    the club has gaps from before tier-5 coverage begins, because we can't
    claim to know those seasons were non-league rather than unseen
    Conference seasons.
    """
    if bucket == OUTSIDE:
        return OUTSIDE_NAME_AMBIGUOUS if coverage_note else OUTSIDE_NAME
    return TIER_NAMES.get(bucket, f"Tier {bucket}")


def the(tier: int) -> str:
    """
    "the Premier League" but bare "League One" — same rule digest.narrative
    already applies to division names.
    """
    name = bucket_name(tier)
    return name if name.startswith("League") else f"the {name}"


def window_buckets(tiers_by_year: dict[int, int]) -> list[int]:
    """
    The club's own window as a flat list of buckets, oldest first. Seasons
    inside the window with no standings row become OUTSIDE.

    The window starts and ends on a recorded season by construction, so it
    can never be all-outside — which is what stops "ever-present" ever
    landing on the outside bucket.
    """
    if not tiers_by_year:
        return []
    first, last = min(tiers_by_year), max(tiers_by_year)
    return [tiers_by_year.get(year, OUTSIDE) for year in range(first, last + 1)]


def distribution(buckets: list[int]) -> dict[str, int]:
    """
    Counts per bucket, JSON-ready with string keys.

    Keyed on BUCKET_LADDER rather than TIER_NAMES, which holds names for
    tiers the standings do not yet reach: naming a level and recording
    seasons in it are different things, and only the second belongs in a
    club's distribution.
    """
    counts = {("outside" if b == OUTSIDE else str(b)): 0 for b in BUCKET_LADDER}
    for b in buckets:
        key = "outside" if b == OUTSIDE else str(b)
        counts[key] = counts.get(key, 0) + 1
    return counts


def primary_tier(buckets: list[int]) -> int:
    """
    The middle of the club's record. median_low rather than median: an
    even split between two divisions resolves to the higher one, and never
    to a fractional tier that rounds somewhere arbitrary.
    """
    return statistics.median_low(sorted(buckets))


def _coverage_note(tiers_by_year: dict[int, int]) -> str | None:
    """Flag clubs whose gaps fall before Tier 5 was being recorded."""
    if not tiers_by_year:
        return None
    first, last = min(tiers_by_year), max(tiers_by_year)
    for year in range(first, last + 1):
        if year in tiers_by_year:
            continue
        if year < TIER5_FIRST_SEASON:
            return "pre-coverage-gap"
    return None


def _spread(buckets: list[int]) -> int:
    """
    How much of the pyramid the club really covers. Buckets appearing only
    once don't count — a Championship club with a single freak season
    shouldn't be described as spanning the whole pyramid.
    """
    counts: dict[int, int] = {}
    for b in buckets:
        counts[b] = counts.get(b, 0) + 1
    repeated = [b for b, n in counts.items() if n >= 2]
    # Measured in rungs of BUCKET_LADDER, not in bucket numbers: with the
    # sentinel at 99 the arithmetic would otherwise report a club that
    # yo-yos in and out of the League as spanning ninety-nine divisions.
    rungs = [BUCKET_LADDER.index(b) for b in repeated if b in BUCKET_LADDER]
    return (max(rungs) - min(rungs) + 1) if rungs else 1


def _adjacent(counts: dict[int, int], primary: int, n: int) -> tuple[int | None, float]:
    """
    The neighbouring bucket a club shares its time with, if any. Ties go to
    the higher division (lower number) rather than falling out of dict order.
    """
    best, best_share = None, 0.0
    if primary not in BUCKET_LADDER:
        return best, best_share
    here = BUCKET_LADDER.index(primary)
    candidates = {BUCKET_LADDER[rung] for rung in (here - 1, here + 1)
                  if 0 <= rung < len(BUCKET_LADDER)}

    # "Outside" is not a rung at a fixed depth: it means below everything
    # this club's record reaches. Tiers 6 and 7 are recorded for seven
    # seasons only, so a club whose gaps fall outside that window has an
    # unrecorded level immediately beneath its own - and Boston United,
    # Dover, Tamworth and Welling all yo-yo across exactly that line. Take
    # it away and the label they earn most clearly is the one they lose.
    recorded = [b for b in counts if b != OUTSIDE and b in BUCKET_LADDER]
    if recorded and primary == max(recorded, key=BUCKET_LADDER.index):
        candidates.add(OUTSIDE)

    for candidate in candidates:
        share = counts.get(candidate, 0) / n
        if share > best_share:
            best, best_share = candidate, share
    return best, best_share


def _label(kind: str, tier: int, second: int | None, note: str | None) -> str:
    name = bucket_name(tier, note)
    if kind == "insufficient":
        return "Insufficient record"
    if tier == OUTSIDE:
        return f"Mostly {name}"
    if kind == "ever-present":
        return f"{name} ever-present"
    if kind == "established":
        return f"Established {name}"
    if kind == "yo-yo":
        low, high = sorted([tier, second])
        return f"{bucket_name(low, note)} / {bucket_name(high, note)} yo-yo club"
    if kind == "broad":
        return f"{name} club (whole-pyramid range)"
    return f"{name} club"


def classify(buckets: list[int], coverage_note: str | None = None) -> dict:
    """
    Summarise a window of buckets into a kind + label. Pure; the DB never
    reaches this far.
    """
    n = len(buckets)
    recorded = sum(1 for b in buckets if b != OUTSIDE)

    if n < MIN_WINDOW or recorded < MIN_RECORDED:
        return {"tier": None, "second_tier": None, "kind": "insufficient",
                "label": "Insufficient record", "share": None}

    counts: dict[int, int] = {}
    for b in buckets:
        counts[b] = counts.get(b, 0) + 1

    primary = primary_tier(buckets)
    share = counts[primary] / n
    adj, adj_share = _adjacent(counts, primary, n)

    if len(counts) == 1:
        kind, second = "ever-present", None
    elif share < 0.60 and adj is not None and (share + adj_share) >= 0.75:
        kind, second = "yo-yo", adj
    elif share >= 0.60:
        kind, second = "established", None
    elif _spread(buckets) >= BROAD_SPREAD:
        kind, second = "broad", None
    else:
        kind, second = "mixed", None

    return {
        "tier": primary,
        "second_tier": second,
        "kind": kind,
        "label": _label(kind, primary, second, coverage_note),
        "share": round(share, 3),
    }


def trend(buckets: list[int]) -> tuple[int | None, str | None]:
    """
    Which way the club is moving: the last RECENT_WINDOW seasons against
    the PRIOR_WINDOW before them. Returns (recent_tier, direction).

    Measuring direction rather than level is the point. A club that fell
    to non-league and has since climbed back is rising, even though its
    recent seasons still sit below its long-run average.
    """
    if len(buckets) < MIN_WINDOW:
        return None, None
    recent = primary_tier(buckets[-RECENT_WINDOW:])
    prior = buckets[-(RECENT_WINDOW + PRIOR_WINDOW):-RECENT_WINDOW]
    if len(prior) < MIN_PRIOR:
        return recent, None
    base = primary_tier(prior)
    if recent < base:
        return recent, "rising"
    if recent > base:
        return recent, "falling"
    return recent, "level"


def natural_level(tiers_by_year: dict[int, int]) -> NaturalLevel:
    """Full natural-level record for one club's season history."""
    buckets = window_buckets(tiers_by_year)
    note = _coverage_note(tiers_by_year)
    c = classify(buckets, note)
    recent, direction = trend(buckets) if c["tier"] is not None else (None, None)

    return NaturalLevel(
        tier=c["tier"],
        second_tier=c["second_tier"],
        kind=c["kind"],
        label=c["label"],
        share=c["share"],
        seasons=len(buckets),
        recorded=sum(1 for b in buckets if b != OUTSIDE),
        distribution=distribution(buckets),
        coverage_note=note,
        recent_tier=recent,
        trend=direction,
    )


def level_gap(nl: NaturalLevel, current_tier: int | None, is_active: bool) -> int | None:
    """
    How far the club currently sits from where it belongs. Positive means
    below its level, negative means above it.

    None for a club that isn't in the latest season: club_trajectory's
    "current tier" is really its last recorded tier, which for a defunct
    club is a decade stale and would generate sentences about where Bury
    currently sit.
    """
    if not is_active or nl.tier is None or current_tier is None:
        return None
    if nl.tier == OUTSIDE:
        return None
    return current_tier - nl.tier


def load_histories(conn: sqlite3.Connection) -> dict[str, dict[int, int]]:
    """{club_id: {season_end_year: tier}} — the only function here touching sqlite."""
    histories: dict[str, dict[int, int]] = {}
    for club_id, year, tier in conn.execute(
        "SELECT club_id, season_end_year, tier FROM standings WHERE club_id IS NOT NULL"
    ):
        histories.setdefault(club_id, {})[year] = tier
    return histories


def distribution_json(nl: NaturalLevel) -> str:
    return json.dumps(nl.distribution)
