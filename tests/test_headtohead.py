"""
Head-to-head: the record against every club a club has played.

The property under test throughout is agreement. The cards, the
superlatives and the table are three renderings of one structure, and the
failure this guards against is the ordinary one - a second query, written
later, that counts something slightly different and puts a number on the
page that contradicts the table beneath it.
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import digest                                            # noqa: E402
import headtohead                                        # noqa: E402

PROJECT_ROOT = Path(__file__).parent.parent
DB = PROJECT_ROOT / "data" / "db" / "england.db"
SITE = PROJECT_ROOT / "site"


@pytest.fixture(scope="module")
def conn():
    if not DB.exists():
        pytest.skip("database not built")
    c = sqlite3.connect(DB)
    yield c
    c.close()


@pytest.fixture(scope="module")
def log(conn):
    return headtohead.match_log(conn)


def _page(club_id):
    path = SITE / "team" / club_id / "index.html"
    if not path.exists():
        pytest.skip("site not built")
    return path.read_text()


def _data(club_id):
    path = SITE / "team" / club_id / "h2h-data.js"
    if not path.exists():
        pytest.skip("site not built")
    raw = path.read_text()
    return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])


def _h2h_rows(html):
    section = html.split('id="h2h-table"', 1)
    if len(section) == 1:
        return []
    body = section[1].split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    rows = []
    for row in re.findall(r"<tr [^>]*data-opponent=\"([^\"]+)\"[^>]*>(.*?)</tr>",
                          body, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row[1], re.S)
        rows.append((row[0], [c.strip() for c in cells]))
    return rows


# ── the structure ──────────────────────────────────────────────────────────

def test_every_row_accounts_for_every_match(conn, log):
    """W + D + L = P on each row, and the rows sum to the club's matches."""
    for club_id, opponents in log.items():
        rows = headtohead.records(opponents)
        for r in rows:
            assert r["won"] + r["drawn"] + r["lost"] == r["played"], (
                f"{club_id} v {r['opponent']} does not add up")
        played = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE (home_club_id = ? OR away_club_id = ?)"
            " AND home_club_id IS NOT NULL AND away_club_id IS NOT NULL",
            (club_id, club_id)).fetchone()[0]
        assert sum(r["played"] for r in rows) == played, club_id


def test_the_record_is_symmetric(conn, log):
    """
    A's wins over B are B's defeats to A - checked against
    digest.head_to_head, which computes the pair independently in SQL and
    is the reference implementation this module was built to replace at
    scale rather than to differ from.
    """
    club_id = "arsenal-fc"
    rows = headtohead.records(log[club_id])
    for r in rows[:12]:
        other = headtohead.records(log[r["opponent"]])
        back = next(x for x in other if x["opponent"] == club_id)
        assert r["won"] == back["lost"]
        assert r["drawn"] == back["drawn"]
        assert r["goals_for"] == back["goals_against"]

        pair = digest.head_to_head(conn, club_id, r["opponent"])
        assert pair["total"] == r["played"]
        assert pair["a_wins"] == r["won"]
        assert pair["b_wins"] == r["lost"]
        assert pair["draws"] == r["drawn"]
        assert pair["first_season"] == r["first_season"]


def test_a_superlative_never_names_a_fixture_below_its_threshold(log):
    """
    "Best record" over three meetings is not a record. Where a club has no
    fixture deep enough the lines are dropped rather than computed thin -
    which is the case for the smallest clubs on the site, and has to stay
    a stated outcome rather than an accident.
    """
    thin = 0
    for club_id, opponents in log.items():
        rows = headtohead.records(opponents)
        summary = headtohead.summary(rows)
        threshold = summary["threshold"]
        if threshold is None:
            thin += 1
            assert summary["best_record"] is None
            assert summary["worst_record"] is None
            continue
        assert threshold in (headtohead.MIN_MEETINGS, headtohead.FLOOR_MEETINGS)
        for key in ("best_record", "worst_record"):
            assert summary[key]["played"] >= threshold, club_id
        for r in summary["never_beaten_by"]:
            assert r["lost"] == 0
            assert r["played"] >= headtohead.UNBEATEN_MEETINGS
    assert thin, "no club is thin enough to exercise the dropped lines"


def test_the_best_record_is_the_best_one(log):
    rows = headtohead.records(log["arsenal-fc"])
    summary = headtohead.summary(rows)
    eligible = [r for r in rows if r["played"] >= summary["threshold"]]
    best = summary["best_record"]["won"] / summary["best_record"]["played"]
    worst = summary["worst_record"]["won"] / summary["worst_record"]["played"]
    assert best == max(r["won"] / r["played"] for r in eligible)
    assert worst == min(r["won"] / r["played"] for r in eligible)


def test_a_database_without_matches_yields_nothing():
    """The module is asked for a log on fixtures that have no matches table."""
    empty = sqlite3.connect(":memory:")
    assert headtohead.match_log(empty) == {}


# ── the page ───────────────────────────────────────────────────────────────

def test_the_cards_agree_with_the_table_beneath_them():
    """
    The whole point of one structure feeding all three renderings. A card
    that disagrees with its own table is the failure a second query would
    eventually produce.
    """
    html = _page("arsenal-fc")
    rows = _h2h_rows(html)
    assert rows, "no head-to-head table on the page"

    cards = dict(
        (label, value) for value, label in re.findall(
            r'<div class="stat-value">(.*?)</div><div class="stat-label">(.*?)</div>',
            html, re.S))
    assert cards["Opponents met"] == str(len(rows))
    played = sum(int(cells[1]) for _, cells in rows)
    assert cards["Matches played"] == f"{played:,}"

    won = sum(int(cells[2]) for _, cells in rows)
    drawn = sum(int(cells[3]) for _, cells in rows)
    lost = sum(int(cells[4]) for _, cells in rows)
    assert cards["Won / drawn / lost"] == f"{won}/{drawn}/{lost}"

    # Most played is the first row, because the server sorts by meetings.
    most_label = next(k for k in cards if k.startswith("Most played"))
    assert cards[most_label] == rows[0][1][0]
    assert most_label.endswith(f"{rows[0][1][1]} meetings")


def test_the_page_says_which_threshold_it_used():
    html = _page("arsenal-fc")
    assert f"met {headtohead.MIN_MEETINGS} or more times" in html, (
        "the page must name the depth its best and worst records are drawn from")


def test_every_opponent_in_the_table_is_in_the_data_file():
    """
    The table is server-rendered and the matches arrive in a sibling file.
    A row whose opponent is missing from that file is a row that opens an
    empty panel - and #vs= links point at exactly these keys.
    """
    for club_id in ("arsenal-fc", "marine-fc"):
        rows = _h2h_rows(_page(club_id))
        data = _data(club_id)
        for opponent, cells in rows:
            entry = data["opponents"].get(opponent)
            assert entry is not None, f"{club_id}: no data for {opponent}"
            assert len(entry["matches"]) == int(cells[1])
            for m in entry["matches"]:
                assert data["divisions"][m[2]], "a match with no division name"


def test_a_vs_link_on_the_rivalries_page_resolves():
    path = SITE / "insights" / "rivalries" / "index.html"
    if not path.exists():
        pytest.skip("site not built")
    html = path.read_text()
    links = re.findall(r'href="\.\./\.\./team/([^/]+)/index\.html#vs=([^"]+)"', html)
    assert links, "the rivalries page carries no link into a head-to-head record"
    for club_id, opponent in links:
        data = _data(club_id)
        assert opponent in data["opponents"], f"{club_id} has no record v {opponent}"


def test_every_rivalry_that_has_been_played_carries_its_record():
    path = SITE / "insights" / "rivalries" / "index.html"
    if not path.exists():
        pytest.skip("site not built")
    html = path.read_text()
    body = html.split("<table", 1)[1].split("</table>", 1)[0]
    rows = re.findall(r"<tr>(.*?)</tr>", body, re.S)[1:]
    scored = 0
    for row in rows:
        cells = [c.strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        met, record = cells[3], cells[4]
        if met.strip() == "—":
            assert record.strip() == "—", "a pair that never met has a record"
            continue
        scored += 1
        played = int(re.sub(r"<[^>]+>", "", met).strip())
        wdl = [int(n) for n in re.sub(r"<[^>]+>", "", record).strip().split("–")]
        assert sum(wdl) == played, f"record {wdl} does not add to {played}"
    assert scored, "no rivalry on the page carries a record"


def test_the_digest_does_not_hardcode_a_season():
    """
    It said "in league play since 1993" over matches starting in 1958/59,
    and would have gone on saying it however far back the record grew.
    """
    source = (PROJECT_ROOT / "src" / "digest.py").read_text()
    line = next(l for l in source.splitlines() if "in league play" in l)
    assert "1993" not in line
    assert "since" not in line or "{since}" in line


# ── links ──────────────────────────────────────────────────────────────────

def test_no_page_links_to_a_file_that_was_not_built():
    """
    The head-to-head work added a link shape - ../../team/<club>/#vs=<club>
    - and a link that resolves nowhere fails silently in a static site.
    This walks every internal href in the built site rather than only the
    new ones, and caught a hand-written /team/liverpool-fc/ in a club
    story: an absolute path, which on GitHub Pages resolves under the
    domain rather than under the project.
    """
    import urllib.parse

    if not SITE.exists():
        pytest.skip("site not built")
    dead = []
    for page in SITE.rglob("*.html"):
        for href in re.findall(r'href="([^"]+)"', page.read_text()):
            if href.startswith(("http", "mailto:", "#")):
                continue
            target = href.split("#")[0]
            if not target:
                continue
            if not (page.parent / urllib.parse.unquote(target)).resolve().exists():
                dead.append(f"{page.relative_to(SITE)} -> {href}")
    assert not dead, "links to pages that do not exist: " + "; ".join(dead[:10])
