"""
Every type of page on the site, in one list.

WHY THIS EXISTS. The site has some 550 pages of about fifty kinds, and
the only way to most of them was to already know where they were. The
club value page was the last of twenty-six tiles on The story and was
linked from nowhere else a visitor would look; its owner could not find
it. The header's Browse menu lists eight indexes. Nothing listed
everything.

HOW IT STAYS TRUE. The list is not written down. It is made at the end
of a build from the pages that build actually wrote. Every page is
claimed by a kind - by its exact address, or by a pattern for the kinds
that are one page per club, season or edition - and a page nothing
claims is not left off: it is listed on its own under "Everything else",
by the title it gave itself, and a test fails until it has a kind. So a
page type added next year appears here the day it is built, whether or
not anyone remembers this file.

WHAT IS HERE AND WHAT IS NOT. Here: the pages no story owns - the home
page, the indexes, the tools. Not here: the story pages, which already
have names, straplines and an order in site_build._stories(); assemble()
is handed that list and files each under its section, so a story's name
is written in one place only.
"""

import re
from dataclasses import dataclass

# The sections, in the order the page shows them.
START, CLUBS, SEASONS, MOVED, WHY, GRIDS, REFERENCE = (
    "Start here", "Clubs", "Seasons and divisions", "The story: what moved",
    "The story: why", "Maps and grids", "Reference",
)
SECTIONS = [START, CLUBS, SEASONS, MOVED, WHY, GRIDS, REFERENCE]
ELSEWHERE = "Everything else"

STORY_SECTION = {"moved": MOVED, "why": WHY, "reference": REFERENCE}
# A story filed somewhere other than its own chapter. Club value is a tool
# people ask for by name, like Compare, so it is listed with the clubs.
STORY_OVERRIDE = {"value": CLUBS}


@dataclass(frozen=True)
class Kind:
    key: str
    section: str
    title: str
    sub: str
    path: str                    # the page a reader starts from
    members: str | None = None   # a pattern for the kind's other pages, where it has them
    each: str = ""               # what one of those is, for "356 pages, one for each club"


# The kinds no story owns, in the order they are listed within a section.
KINDS = [
    Kind("home", START, "Home",
         "This week's sentence, the Replay, this week's lines and the current tables.", "index.html"),
    Kind("replay", START, "The Replay",
         "Every club as a dot in its own colours, moving through every season on record.", "replay/index.html"),
    Kind("story", START, "The story",
         "Every finding in reading order: what moved, then why.", "insights/index.html"),
    Kind("teams", CLUBS, "Teams",
         "Find a club: search, A to Z, or by division. Each club has a page of its own.", "teams/index.html",
         r"team/[^/]+/index\.html", "club"),
    Kind("club-table", CLUBS, "All clubs, all data",
         "Every club in one table, with every column the data supports. Sort on any of them.",
         "teams/table/index.html"),
    Kind("compare", CLUBS, "Compare",
         "Any two clubs side by side: record, form, meetings, money and catchment.", "compare/index.html"),
    Kind("seasons", SEASONS, "Seasons",
         "Every season's tables, top to bottom.", "seasons/index.html", r"season/[^/]+/index\.html", "season"),
    Kind("divisions", SEASONS, "Divisions",
         "Each division through time: champions, promotions, relegations.", "division/index.html",
         r"division/[^/]+/index\.html", "division"),
    Kind("fixtures", SEASONS, "Fixtures",
         "The coming week by tier. Each match links to a comparison of the two clubs.", "fixtures/index.html"),
    Kind("matrix", GRIDS, "The Matrix",
         "Every level in every season as one grid. Tap a club to light up its path.", "matrix/index.html"),
    Kind("map", GRIDS, "Groundhop Map",
         "Every ground on a map, with a season slider and distances from a postcode.", "map/index.html"),
    Kind("themes", REFERENCE, "Themes",
         "The theme tables together: administration, points deductions, phoenix clubs, fan-owned clubs.",
         "themes/index.html"),
    Kind("sources", REFERENCE, "Sources",
         "Where every number came from, page by page, with licences.", "sources/index.html"),
    Kind("digest", REFERENCE, "The emails",
         "Every edition of the weekday emails, as sent.", "digest/index.html", r"digest/[^/]+/.+\.html", "edition"),
    Kind("pages", REFERENCE, "All pages", "This list.", "pages/index.html"),
]

# Other words people look for a page under. Not shown; the search box on
# the index matches them. "Club value" was "Which club to buy" for months.
ALSO = {
    "value": "which club to buy price worth investment takeover",
    "teams": "clubs find a club search",
    "club-table": "spreadsheet csv download every column",
    "compare": "head to head versus two clubs",
    "replay": "animation pyramid dots play",
    "matrix": "grid every season every division",
    "map": "grounds stadiums postcode distance",
    "digest": "newsletter editions archive preview review",
    "natural-level": "level punching above below",
    "hatred": "disliked hated rivals",
    "the-pyramid": "league system tiers steps structure",
}

# Pages that exist and are deliberately not listed, with the reason.
HIDDEN = {
    "404.html": "served for any address with no page behind it",
    "chart/index.html": "a redirect: the old chart page sends its readers to Compare",
}


def search_key(text: str) -> str:
    """Lower case, letters and digits only: the form static/search.js reduces a query to."""
    return " ".join("".join(c if c.isalnum() else " " for c in text.lower()).split())


def _story_members(path: str) -> str | None:
    """
    A story whose page is one of a family - a page per measure, or per
    season - owns everything under its own folder: insights/finances/
    holds fourteen pages and the story links to one of them.
    """
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "insights":
        return rf"insights/{re.escape(parts[1])}/.+\.html"
    return None


def assemble(built: list[str], stories: list[dict], examples: dict[str, dict] | None = None) -> dict:
    """
    The index, from the pages a build wrote.

    `built` is every .html file under the site root, as paths from it.
    `stories` is site_build._stories(): dicts with slug, name, sub, section
    and path. `examples` gives, for a kind with many pages, one of them to
    show: {kind key: {"name", "path"}}.

    Returns {"sections": [{"name", "entries": [...]}], "unclaimed": [...],
    "total", "kinds"}. An entry is {"key", "title", "sub", "path", "count",
    "each", "example"}; count is the kind's pages beyond the one linked,
    and nought for a kind that is a single page. Only kinds whose starting
    page was built are listed.
    """
    examples = examples or {}
    on_disk = set(built)
    claimed: set[str] = set()
    by_section: dict[str, list[dict]] = {name: [] for name in SECTIONS}

    def add(key, section, title, sub, path, members, each):
        if path not in on_disk:
            return
        mine = {path}
        if members:
            pattern = re.compile(members)
            mine |= {p for p in on_disk if pattern.fullmatch(p)}
        mine -= claimed          # first come, first served: a page is listed once
        claimed.update(mine)
        # Every line under a name ends the same way, whoever wrote it:
        # the stories' straplines have no full stop and the kinds' do.
        sub = sub if sub.endswith((".", "?", "!")) else sub + "."
        by_section[section].append({
            "key": key, "title": title, "sub": sub, "path": path,
            "count": len(mine - {path}), "each": each, "example": examples.get(key),
            "search": search_key(f"{title} {sub} {ALSO.get(key, '')}"),
        })

    for kind in KINDS:
        add(kind.key, kind.section, kind.title, kind.sub, kind.path, kind.members, kind.each)
    fixed_paths = {kind.path for kind in KINDS}
    for story in stories:
        if story["path"] in fixed_paths:
            continue             # the emails, the sources page: already listed, in their own words
        section = STORY_OVERRIDE.get(story["slug"], STORY_SECTION.get(story["section"], REFERENCE))
        add(story["slug"], section, story["name"], story["sub"], story["path"],
            _story_members(story["path"]), "page")

    unclaimed = sorted(on_disk - claimed - set(HIDDEN))
    sections = [{"name": name, "entries": by_section[name]} for name in SECTIONS if by_section[name]]
    return {
        "sections": sections,
        "unclaimed": unclaimed,
        "total": len(on_disk - set(HIDDEN)),
        "kinds": sum(len(s["entries"]) for s in sections),
    }
