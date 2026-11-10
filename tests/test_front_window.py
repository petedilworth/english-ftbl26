"""
The front window: the pitch at the top of every page, the Replay, the
index of every type of page, and what a link to any page looks like
before it is opened - built from the same small fixture the rest of the
site tests use.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import brand  # noqa: E402
import cards  # noqa: E402
from site_build import SiteBuilder  # noqa: E402
from test_site_build import _db_on_disk  # noqa: E402

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """One build without images, shared: these tests only read it."""
    tmp = tmp_path_factory.mktemp("front")
    out = tmp / "site"
    SiteBuilder(_db_on_disk(tmp), out, charts_enabled=False).build()
    return out


def _page(site, rel):
    return (site / rel).read_text(encoding="utf-8")


# ── The Replay ────────────────────────────────────────────────────────────

def test_the_replay_page_and_its_data_are_built(site):
    data = json.loads(_page(site, "data/pyramid.json"))
    assert data["first"] == 2022 and len(data["seasons"]) == data["last"] - data["first"] + 1
    page = _page(site, "replay/index.html")
    assert 'class="replay"' in page and 'data-src="../data/pyramid.json"' in page and "data-hash" in page
    assert 'src="../static/replay.js"' in page and 'src="../static/hash-state.js"' in page
    # A page with the script switched off still says where the same record is as a table.
    assert "<noscript>" in page and "../matrix/index.html" in page
    # Every club the file offers a link for has a page to link to.
    for club in data["clubs"]:
        assert club[0] is None or (site / "team" / club[0] / "index.html").exists()


def test_the_journeys_offered_are_clubs_with_pages_and_seasons_in_the_record(site):
    page = _page(site, "replay/index.html")
    journeys = re.findall(r'data-replay-club="([^"]+)" data-replay-from="(\d+)"', page)
    assert journeys, "the fixture has a hero, so there is at least one journey"
    data = json.loads(_page(site, "data/pyramid.json"))
    for club, start in journeys:
        assert (site / "team" / club / "index.html").exists()
        assert data["first"] <= int(start) <= data["last"]
    assert len({c for c, _ in journeys}) == len(journeys), "a club is offered once"


def test_the_home_page_puts_its_sentence_on_the_pitch_and_the_replay_under_it(site):
    home = _page(site, "index.html")
    pitch = home[home.index('<div class="pitch">'):home.index('<main id="main"')]
    # The header and the hero are one piece of grass; the Replay is the first thing on the light page.
    assert '<header class="site-header">' in pitch and 'class="hero-band"' in pitch and 'class="hero-line"' in pitch
    main = home[home.index('<main id="main"'):]
    assert 'class="hero-line"' not in main
    assert 'class="replay"' in main and "data-loop" in main and 'data-src="./data/pyramid.json"' in main
    assert main.index('class="replay"') < main.index("The tables"), "the Replay comes before the tables"
    assert 'src="./static/replay.js"' in home
    # Every other page gets the pitch as its header and nothing more.
    team = _page(site, "team/giant-fc/index.html")
    assert '<div class="pitch">' in team and 'class="hero-band"' not in team


def test_the_birthday_picker_has_gone_and_left_nothing_behind(site):
    """
    It was live for a day: a form on the home page, a page of its own, a
    page and a preview card for every club it could assign, a link in the
    header, and a club kept in the visitor's browser. None of it is built,
    nothing links to it, and the one thing it left on people's devices is
    removed by the script every page loads.
    """
    assert not (site / "allocation").exists()
    for page in site.rglob("*.html"):
        if "digest" in page.parts:
            continue
        text = page.read_text(encoding="utf-8")
        for trace in ("allocation/", "alloc-form", "nav-club", "date of birth", "appeals process"):
            assert trace not in text, f"{page.relative_to(site)} still has {trace!r}"
    static = ROOT / "static"
    assert not (static / "allocation.js").exists() and not (static / "allocation-process.js").exists()
    assert not (ROOT / "src" / "allocation.py").exists()
    nav = (static / "nav.js").read_text(encoding="utf-8")
    assert 'localStorage.removeItem("ais.club")' in nav and "getItem" not in nav
    for script in static.glob("*.js"):
        if script.name != "nav.js":
            assert "ais.club" not in script.read_text(encoding="utf-8"), script.name


# ── What a link looks like ────────────────────────────────────────────────

def test_every_page_says_what_it_is_and_where_it_lives(site):
    assert f"<title>{brand.NAME} — {brand.STRAPLINE}</title>" in _page(site, "index.html")
    assert f'<meta property="og:title" content="{brand.NAME} — {brand.STRAPLINE}">' in _page(site, "index.html")
    for rel in ("index.html", "team/giant-fc/index.html", "insights/index.html", "replay/index.html",
                "pages/index.html", "matrix/index.html"):
        page = _page(site, rel)
        if rel != "index.html":
            assert f"— {brand.NAME}</title>" in page
        assert re.search(r'<meta name="description" content="[^"]{40,}">', page), rel
        assert f'<link rel="canonical" href="{brand.page_url(rel)}">' in page
        assert '<meta property="og:title"' in page and f'<meta property="og:site_name" content="{brand.NAME}">' in page
        assert 'rel="icon" href="' in page and "static/favicon.svg" in page
        # A phone paints its own bars the colour of the pitch.
        assert f'<meta name="theme-color" content="{brand.PITCH}">' in page
    team = _page(site, "team/giant-fc/index.html")
    assert "Giant FC: " in re.search(r'<meta name="description" content="([^"]+)"', team).group(1)


def test_no_card_is_offered_by_a_build_that_draws_none(site):
    # og:image must never point at a file that is not there.
    for rel in ("index.html", "team/giant-fc/index.html", "pages/index.html"):
        assert "og:image" not in _page(site, rel) and "apple-touch-icon" not in _page(site, rel)
    assert not (site / "cards").exists()


@pytest.mark.skipif(not cards.available(), reason="this Pillow cannot read the font")
def test_a_build_with_images_draws_a_card_for_every_page_that_names_one(tmp_path):
    out = tmp_path / "site"
    SiteBuilder(_db_on_disk(tmp_path), out, charts_enabled=True).build()
    named = set()
    for page in out.rglob("*.html"):
        if "digest" in page.parts:
            continue
        for image in re.findall(r'<meta property="og:image" content="([^"]+)"', page.read_text(encoding="utf-8")):
            assert image.startswith(brand.SITE_URL + "/cards/"), image
            named.add(image[len(brand.SITE_URL) + 1:])
    assert {"cards/home.png", "cards/replay.png", "cards/team/giant-fc.png", "cards/team/steady-fc.png"} <= named
    for rel in named:
        assert (out / rel).exists(), f"{rel} is named by a page and was not drawn"
    # And nothing is drawn that no page names: the picker's cards went with it.
    drawn = {p.relative_to(out).as_posix() for p in (out / "cards").rglob("*.png")}
    assert drawn == named, drawn ^ named
    manifest = json.loads((out / "site.webmanifest").read_text())
    assert manifest["name"] == brand.NAME and all((out / i["src"]).exists() for i in manifest["icons"])
    assert manifest["theme_color"] == brand.PITCH
    assert (out / "apple-touch-icon.png").exists()


def test_the_page_served_for_a_missing_address_links_absolutely(site):
    page = _page(site, "404.html")
    assert "not in the record" in page and '<meta name="robots" content="noindex">' in page
    assert 'rel="canonical"' not in page
    links = re.findall(r'(?:href|src)="([^"#]+)"', page)
    assert links and all(link.startswith(("https://", "http://")) for link in links), \
        [link for link in links if not link.startswith("http")]
    assert f'{brand.SITE_URL}/static/style.css' in links


def test_the_header_links_resolve_from_every_depth(site):
    for rel in ("index.html", "replay/index.html", "team/giant-fc/index.html", "pages/index.html",
                "insights/fallen-giants/index.html"):
        page = _page(site, rel)
        header = page[page.index('<header class="site-header">'):page.index("</header>")]
        for href in re.findall(r'href="([^"]+)"', header):
            target = (site / rel).parent / href
            assert target.resolve().exists(), f"{rel}: {href}"
        assert "replay/index.html" in header and "pages/index.html" in header


def test_the_new_pages_link_only_to_things_that_were_built(site):
    for rel in ("replay/index.html", "pages/index.html", "index.html"):
        page = _page(site, rel)
        for link in re.findall(r'(?:href|src)="([^"#]+)', page):
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            target = ((site / rel).parent / link).resolve()
            assert target.exists(), f"{rel} links to {link}, which this build did not make"


# ── The scripts ───────────────────────────────────────────────────────────

@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_every_script_parses():
    for script in sorted((ROOT / "static").glob("*.js")):
        done = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
        assert done.returncode == 0, f"{script.name}: {done.stderr}"


def test_the_scripts_and_the_data_agree_on_the_file_format():
    import pyramid
    replay = (ROOT / "static" / "replay.js").read_text(encoding="utf-8")
    # replay.js names what it shows for each kind by position; pyramid.KINDS is the order.
    words = re.search(r"var KIND_WORDS = \[(.*?)\];", replay, re.S).group(1)
    assert len(re.findall(r'"[^"]*"', words)) == len(pyramid.KINDS)
    assert pyramid.KINDS.index("In progress") == 6 and pyramid.KINDS.index("Champions") == 1
