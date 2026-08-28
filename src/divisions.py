"""
The divisions of English football, as one registry.

WHY THIS EXISTS. Until now a tier and a division were the same thing here,
so "tier" was used as the key for the URL slug, the display name, the
download code and the chart colour, in four separate hardcoded tables. The
sixth tier is the first level that is not one division - National League
North and South - and the seventh is four. Once a tier can hold several
divisions, a tier number cannot address a league table, and four tables
that must agree with each other become four chances to add a division in
one place and forget it in another.

WHAT IS AND IS NOT IN HERE. Identity: which divisions exist, at what
level, in what order, under what URL, and whether they can be downloaded.
NOT era renames - the Second Division became the First Division became the
Championship, and that lookup stays in aggregate.division_name(), which is
what keeps /division/championship/ covering 1993/94 onward under three
different names.

THE SLUG IS THE ID. For tiers 1-5 every division_id is the URL slug the
site already publishes, so nothing that exists today changes address.

NOT A DATABASE TABLE. Nothing needs to join against division metadata, and
a table would be a fifth thing to keep in sync.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Division:
    division_id: str
    tier: int
    name: str
    sort_order: int          # position within its own tier, for display
    source_code: str | None  # football-data.co.uk code; None means not fetchable
    color: str               # the tier's colour on the charts
    # The seasons the division existed, by the year each ended. Both None
    # for a division that has always been there. The Southern League
    # Premier was one division until 2017/18 and two from 2018/19, so a
    # registry that cannot say when is a registry that has to lie about
    # one of them.
    first_season: int | None = None
    last_season: int | None = None

    def existed_in(self, season_end_year: int) -> bool:
        if self.first_season is not None and season_end_year < self.first_season:
            return False
        if self.last_season is not None and season_end_year > self.last_season:
            return False
        return True


# Colours are per tier rather than per division: two divisions at the same
# level are the same level, and colouring them apart would say otherwise.
TIER_COLORS = {
    1: "#5e35b1",
    2: "#1e88e5",
    3: "#43a047",
    4: "#fb8c00",
    5: "#e53935",
    6: "#8d6e63",
    7: "#546e7a",
}

DIVISIONS: list[Division] = [
    Division("premier-league", 1, "Premier League", 1, "E0", TIER_COLORS[1]),
    Division("championship", 2, "Championship", 1, "E1", TIER_COLORS[2]),
    Division("league-one", 3, "League One", 1, "E2", TIER_COLORS[3]),
    Division("league-two", 4, "League Two", 1, "E3", TIER_COLORS[4]),
    Division("national-league", 5, "National League", 1, "EC", TIER_COLORS[5]),
    # Below the fifth tier there is no match-level feed to download, so
    # these carry no source_code and download.download_all skips them.
    Division("national-league-north", 6, "National League North", 1, None,
             TIER_COLORS[6]),
    Division("national-league-south", 6, "National League South", 2, None,
             TIER_COLORS[6]),
    Division("isthmian-league-premier", 7, "Isthmian League Premier", 1, None,
             TIER_COLORS[7]),
    Division("northern-premier-league-premier", 7,
             "Northern Premier League Premier", 2, None, TIER_COLORS[7]),
    # One division until 2017/18, then two. All three ids are real: the
    # single one is not a predecessor of either half, it is the thing that
    # was split, and its seasons belong under its own name.
    Division("southern-league-premier", 7, "Southern League Premier", 3, None,
             TIER_COLORS[7], last_season=2018),
    Division("southern-league-premier-central", 7,
             "Southern League Premier Central", 4, None, TIER_COLORS[7],
             first_season=2019),
    Division("southern-league-premier-south", 7,
             "Southern League Premier South", 5, None, TIER_COLORS[7],
             first_season=2019),
]

BY_ID = {d.division_id: d for d in DIVISIONS}


def by_tier(tier: int, season_end_year: int | None = None) -> list[Division]:
    """
    Every division at a level, in display order.

    With a season, only the divisions that existed in it - which is what
    "how many divisions does this tier have" means for any question about
    a particular year.
    """
    found = (d for d in DIVISIONS if d.tier == tier)
    if season_end_year is not None:
        found = (d for d in found if d.existed_in(season_end_year))
    return sorted(found, key=lambda d: d.sort_order)


def tiers() -> list[int]:
    """Every level, top first."""
    return sorted({d.tier for d in DIVISIONS})


def sole_division(tier: int) -> Division | None:
    """
    The division of a tier that has exactly one.

    The bridge from the old world to the new: every row written before
    division_id existed belongs to a tier that had one division, so this
    is how those rows get an id without anybody deciding anything.
    """
    divisions = by_tier(tier)
    return divisions[0] if len(divisions) == 1 else None


def parallel_at(tier: int, season_end_year: int) -> bool:
    """Whether a level held more than one division in a given season."""
    return len(by_tier(tier, season_end_year)) > 1
