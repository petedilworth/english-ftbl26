"""The index of every type of page: made from what was built, with nothing left off it."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import pageindex  # noqa: E402
from site_build import SiteBuilder  # noqa: E402
from test_site_build import _db_on_disk  # noqa: E402

ROOT = Path(__file__).parent.parent

STORIES = [
    {"slug": "yo-yo", "name": "Yo-yo clubs", "sub": "Bounce runs", "section": "moved",
     "path": "insights/yo-yo/index.html"},
    {"slug": "finances", "name": "Club finances", "sub": "Revenue, wages, profit and debt", "section": "why",
     "path": "insights/finances/revenue/2025-26/index.html"},
    {"slug": "administration", "name": "Clubs that entered administration", "sub": "One table", "section": "why",
     "path": "themes/administration/index.html"},
    {"slug": "value", "name": "Club value", "sub": "Fourteen levers – you set the weights", "section": "why",
     "path": "insights/value/index.html"},
    {"slug": "sources", "name": "Sources", "sub": "The story's own words for it", "section": "reference",
     "path": "sources/index.html"},
    {"slug": "timeline", "name": "Timeline", "sub": "Notable events", "section": "reference",
     "path": "insights/timeline/index.html"},
    {"slug": "luck", "name": "Luck", "sub": "A page this build did not make", "section": "moved",
     "path": "insights/luck/index.html"},
]
BUILT = [
    "index.html", "404.html", "chart/index.html", "pages/index.html", "insights/index.html",
    "teams/index.html", "team/a-fc/index.html", "team/b-fc/index.html", "team/c-fc/index.html",
    "seasons/index.html", "season/2024-25/index.html", "sources/index.html", "themes/index.html",
    "themes/administration/index.html", "insights/yo-yo/index.html", "insights/value/index.html",
    "insights/finances/revenue/2025-26/index.html", "insights/finances/revenue/2024-25/index.html",
    "insights/finances/wages/2025-26/index.html", "insights/timeline/index.html",
    "digest/index.html", "digest/preview/2026-10-30/index.html", "digest/preview/2026-10-30/email.html",
]


def _entries(index):
    return {e["key"]: dict(e, section=s["name"]) for s in index["sections"] for e in s["entries"]}


def test_a_kind_is_listed_only_if_its_first_page_was_built():
    index = pageindex.assemble(BUILT, STORIES)
    entries = _entries(index)
    assert "home" in entries and "teams" in entries and "yo-yo" in entries
    for absent in ("replay", "matrix", "map", "compare", "fixtures", "luck"):
        assert absent not in entries, absent
    # Sections keep their order, and one with nothing in it is not shown.
    names = [s["name"] for s in index["sections"]]
    assert names == [n for n in pageindex.SECTIONS if n in names] and pageindex.GRIDS not in names
    assert index["unclaimed"] == []


def test_a_kind_with_many_pages_says_how_many_and_shows_one():
    example = {"name": "B FC", "path": "team/b-fc/index.html"}
    entries = _entries(pageindex.assemble(BUILT, STORIES, {"teams": example}))
    assert (entries["teams"]["count"], entries["teams"]["each"], entries["teams"]["example"]) == (3, "club", example)
    assert (entries["seasons"]["count"], entries["seasons"]["each"]) == (1, "season")
    assert entries["digest"]["count"] == 2 and entries["home"]["count"] == 0
    # A story that is one of a family owns its folder: the link goes to one page and the rest are counted.
    assert entries["finances"]["path"] == "insights/finances/revenue/2025-26/index.html"
    assert entries["finances"]["count"] == 2 and entries["yo-yo"]["count"] == 0


def test_club_value_is_filed_with_the_clubs_under_the_name_people_use():
    entries = _entries(pageindex.assemble(BUILT, STORIES))
    value = entries["value"]
    assert value["title"] == "Club value" and value["section"] == pageindex.CLUBS
    assert value["sub"] == "Fourteen levers – you set the weights."        # the full stop is added
    # Found under its old name as well as its new one.
    assert "which club to buy" in value["search"] and value["search"].startswith("club value")
    assert pageindex.search_key("A–Z, by Division!") == "a z by division"


def test_stories_go_under_their_chapter_and_a_page_is_listed_once():
    entries = _entries(pageindex.assemble(BUILT, STORIES))
    assert entries["yo-yo"]["section"] == pageindex.MOVED
    assert entries["administration"]["section"] == pageindex.WHY
    assert entries["timeline"]["section"] == pageindex.REFERENCE
    # The sources page is a kind and a story: it is listed once, in the kind's words.
    listed = [e for e in entries.values() if e["path"] == "sources/index.html"]
    assert len(listed) == 1 and listed[0]["key"] == "sources" and "licences" in listed[0]["sub"]
    paths = [e["path"] for e in entries.values()]
    assert len(paths) == len(set(paths))


def test_a_page_nothing_claims_is_reported_and_the_hidden_ones_are_not():
    index = pageindex.assemble(BUILT + ["mystery/index.html", "team/a-fc/notes.html"], STORIES)
    assert index["unclaimed"] == ["mystery/index.html", "team/a-fc/notes.html"]
    assert set(pageindex.HIDDEN) == {"404.html", "chart/index.html"}
    # The count on the page is of pages a visitor can be sent to.
    assert index["total"] == len(BUILT) + 2 - len(pageindex.HIDDEN)
    assert index["kinds"] == len(_entries(index))


def test_every_kind_is_spelt_out_once():
    keys = [k.key for k in pageindex.KINDS]
    assert len(keys) == len(set(keys)) and len({k.path for k in pageindex.KINDS}) == len(keys)
    for kind in pageindex.KINDS:
        assert kind.section in pageindex.SECTIONS and kind.title and kind.sub.endswith(".")
        assert bool(kind.members) == bool(kind.each), kind.key
        if kind.members:
            assert not re.fullmatch(kind.members, kind.path), f"{kind.key}: the first page is not one of its own members"
    assert set(pageindex.ALSO) - set(keys) <= {"value", "natural-level", "hatred", "the-pyramid"}


# ── The page itself ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def site(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pages")
    out = tmp / "site"
    SiteBuilder(_db_on_disk(tmp), out, charts_enabled=False).build()
    return out


def _unlisted(site):
    """Built pages the index neither links to nor counts under a kind."""
    built = sorted(p.relative_to(site).as_posix() for p in site.rglob("*.html"))
    page = (site / "pages" / "index.html").read_text(encoding="utf-8")
    linked = {link.removeprefix("../") for link in re.findall(r'href="(\.\./[^"#]+)"', page)}
    patterns = [re.compile(k.members) for k in pageindex.KINDS if k.members]
    patterns += [re.compile(pageindex._story_members(link)) for link in linked if pageindex._story_members(link)]
    return [p for p in built
            if p not in linked and p not in pageindex.HIDDEN and not any(pt.fullmatch(p) for pt in patterns)]


def test_the_index_lists_itself_and_everything_else_the_build_made(site):
    page = (site / "pages" / "index.html").read_text(encoding="utf-8")
    assert "<h1>All pages</h1>" in page and 'href="../pages/index.html">All pages</a>' in page
    assert pageindex.ELSEWHERE not in page, "a page in the fixture build has no kind"
    assert _unlisted(site) == []
    for link in re.findall(r'href="(\.\./[^"#]+)"', page):
        assert (site / "pages" / link).resolve().exists(), link
    # The filter box works off data-name, through the same script as the teams index.
    assert "data-live-filter" in page and 'src="../static/search.js"' in page
    assert page.count('<li data-name="') == len(re.findall(r'class="page-index-title"', page))
    assert 'data-name="home ' in page
    search = (ROOT / "static" / "search.js").read_text(encoding="utf-8")
    assert "data-live-filter" in search and "team-search" in search


def test_the_index_counts_what_is_there(site):
    page = (site / "pages" / "index.html").read_text(encoding="utf-8")
    clubs = len(list((site / "team").iterdir()))
    assert f"Plus {clubs} pages, one for each club" in page
    built = len([p for p in site.rglob("*.html") if p.relative_to(site).as_posix() not in pageindex.HIDDEN])
    assert f"{built} pages" in page
    # The example club is one with a page, and the hero if there is one.
    assert re.search(r'for example, <a href="\.\./team/giant-fc/index\.html">Giant FC</a>', page)


def test_every_page_can_reach_the_index(site):
    for rel in ("index.html", "team/giant-fc/index.html", "insights/index.html", "404.html"):
        page = (site / rel).read_text(encoding="utf-8")
        assert page.count("pages/index.html") >= 2, f"{rel}: the header and the footer both link to it"


def test_the_real_site_has_no_page_without_a_kind():
    """
    The check that matters, against the site as it is actually built: if
    a new type of page has been added and src/pageindex.py does not know
    it, the page appears under "Everything else" and this fails.
    """
    real = ROOT / "site"
    if not (real / "pages" / "index.html").exists():
        pytest.skip("site not built")
    page = (real / "pages" / "index.html").read_text(encoding="utf-8")
    assert pageindex.ELSEWHERE not in page
    assert _unlisted(real) == []
    assert 'href="../insights/value/index.html">Club value</a>' in page
