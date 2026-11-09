"""
The front window: the Replay, the allocation, and what a link to any page
looks like before it is opened - built from the same small fixture the
rest of the site tests use.
"""

import json
import re
import shutil
import sqlite3
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


def test_the_home_page_carries_the_replay_and_the_form(site):
    home = _page(site, "index.html")
    assert 'class="replay"' in home and "data-loop" in home and 'data-src="./data/pyramid.json"' in home
    # The home page's form hands the date to the allocation page; it does not run there.
    assert 'id="alloc-form"' in home and 'data-go="./allocation/index.html"' in home
    for script in ("replay.js", "allocation-process.js", "allocation.js"):
        assert f'src="./static/{script}"' in home


# ── The allocation ────────────────────────────────────────────────────────

def test_the_allocation_page_its_data_and_a_page_per_club(site):
    index = json.loads(_page(site, "allocation/data/index.json"))
    assert index["epoch"] == "2025-03-01" and index["straight"] == []
    for season, *_ in index["seasons"]:
        data = json.loads(_page(site, f"allocation/data/{season}.json"))
        assert data["season"] == season and len(data["m"]) % 5 == 0 and sum(data["sizes"]) == len(data["clubs"])
    page = _page(site, "allocation/index.html")
    assert 'id="alloc-form"' in page and "data-go" not in page and 'id="alloc-result"' in page
    assert 'autocomplete="bday-day"' in page and 'inputmode="numeric"' in page
    assert "There is no appeals process." in page and "1 March 2025" in page
    for club in ("giant-fc", "steady-fc"):
        shared = _page(site, f"allocation/{club}/index.html")
        assert "Someone you know has been assigned" in shared and f'href="../../team/{club}/index.html"' in shared
        assert 'data-index="../../allocation/data/index.json"' in shared
        assert '<meta name="robots" content="noindex">' in shared
    assert "eighth in League One" in _page(site, "allocation/giant-fc/index.html")


def test_no_page_puts_a_date_of_birth_in_an_address():
    """
    The promise the form makes. The date may be handed between pages in
    sessionStorage and nowhere else: not a query string, not a fragment,
    not localStorage, not a request.
    """
    js = (ROOT / "static" / "allocation.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in js.splitlines() if not line.strip().startswith(("//", "*", "/*")))
    assert "sessionStorage.setItem(HANDOFF, iso)" in code and "sessionStorage.removeItem(HANDOFF)" in code
    assert not re.search(r"location\.(hash|search)\s*=", code)
    assert not re.search(r"[?&#]d=|\?dob|\?date", code)
    # The only thing kept is the club; the only thing fetched is the record.
    stored = re.findall(r"localStorage\.setItem\(([^,]+),", code)
    assert stored == ["STORE"] and "JSON.stringify(club)" in code
    assert "remember({id: a.club, name: name, a: colourA, b: colourB})" in code
    fetched = re.findall(r"getJSON\(([^)]*)\)", code)
    assert fetched and all("INDEX_URL" in f or "PYRAMID_URL" in f or f == "url" for f in fetched), fetched
    assert "XMLHttpRequest" not in code and "sendBeacon" not in code


def test_the_straight_tone_list_reaches_the_page(tmp_path, monkeypatch):
    from editions import config
    listed = tmp_path / "straight.yml"
    listed.write_text("- date: 1989-04-15\n  note: x\n- clubs: [giant-fc]\n  note: y\n", encoding="utf-8")
    monkeypatch.setattr(config, "STRAIGHT_DATES", listed)
    import editions.tone as tone
    monkeypatch.setattr(tone.load, "__defaults__", (listed,))
    out = tmp_path / "site"
    SiteBuilder(_db_on_disk(tmp_path), out, charts_enabled=False).build()
    index = json.loads((out / "allocation" / "data" / "index.json").read_text())
    assert index["straight"] == [{"md": "04-15", "clubs": []}, {"md": None, "clubs": ["giant-fc"]}]


def test_a_database_that_cannot_run_the_process_builds_without_it(tmp_path):
    db = _db_on_disk(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE matches SET match_date = NULL")
    conn.commit()
    conn.close()
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()
    assert not (out / "allocation").exists()
    home = (out / "index.html").read_text()
    assert "allocation" not in home and 'id="nav-club"' not in home
    assert (out / "replay" / "index.html").exists()      # the Replay needs no dates


# ── What a link looks like ────────────────────────────────────────────────

def test_every_page_says_what_it_is_and_where_it_lives(site):
    assert f"<title>{brand.NAME} — {brand.STRAPLINE}</title>" in _page(site, "index.html")
    assert f'<meta property="og:title" content="{brand.NAME} — {brand.STRAPLINE}">' in _page(site, "index.html")
    for rel in ("index.html", "team/giant-fc/index.html", "insights/index.html", "replay/index.html",
                "allocation/index.html", "matrix/index.html"):
        page = _page(site, rel)
        if rel != "index.html":
            assert f"— {brand.NAME}</title>" in page
        assert re.search(r'<meta name="description" content="[^"]{40,}">', page), rel
        assert f'<link rel="canonical" href="{brand.page_url(rel)}">' in page
        assert '<meta property="og:title"' in page and f'<meta property="og:site_name" content="{brand.NAME}">' in page
        assert 'rel="icon" href="' in page and "static/favicon.svg" in page
    team = _page(site, "team/giant-fc/index.html")
    assert "Giant FC: " in re.search(r'<meta name="description" content="([^"]+)"', team).group(1)


def test_no_card_is_offered_by_a_build_that_draws_none(site):
    # og:image must never point at a file that is not there.
    for rel in ("index.html", "team/giant-fc/index.html", "allocation/giant-fc/index.html"):
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
    assert {"cards/home.png", "cards/allocation.png", "cards/replay.png", "cards/team/giant-fc.png",
            "cards/allocation/giant-fc.png"} <= named
    for rel in named:
        assert (out / rel).exists(), f"{rel} is named by a page and was not drawn"
    manifest = json.loads((out / "site.webmanifest").read_text())
    assert manifest["name"] == brand.NAME and all((out / i["src"]).exists() for i in manifest["icons"])
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
    for rel, depth in (("index.html", 0), ("replay/index.html", 1), ("team/giant-fc/index.html", 2),
                       ("allocation/giant-fc/index.html", 2)):
        page = _page(site, rel)
        header = page[page.index('<header class="site-header">'):page.index("</header>")]
        for href in re.findall(r'href="([^"]+)"', header):
            target = (site / rel).parent / href
            assert target.resolve().exists(), f"{rel}: {href}"
        assert 'id="nav-club"' in header and "replay/index.html" in header


def test_the_new_pages_link_only_to_things_that_were_built(site):
    for rel in ("replay/index.html", "allocation/index.html", "allocation/steady-fc/index.html", "index.html"):
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
    process = (ROOT / "static" / "allocation-process.js").read_text(encoding="utf-8")
    import allocation
    for code in allocation.TIEBREAK_CODE.values():
        assert f'"{code}"' in process or code == "gd"       # goal difference is the script's default branch
