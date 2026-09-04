"""
The generated club summaries have to be true, and must not crowd out a
written one.

Two thirds of the clubs here are below the fifth tier and will not get a
written history soon, so 235 club pages had nothing but "The written
history of X is still to come." The replacement is assembled from the
club's own rows - and because these are small clubs, a plausible
invented sentence about one would be indistinguishable from a true one.
So every claim is checked against the database rather than read for
plausibility.
"""
import html
import re
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DB = PROJECT_ROOT / "data" / "db" / "england.db"
SITE = PROJECT_ROOT / "site"
CONTENT = PROJECT_ROOT / "content"
MARKER = "Drawn from the record rather than written"


def _conn():
    if not DB.exists():
        pytest.skip("no built database")
    return sqlite3.connect(DB)


def _pages():
    pages = sorted(SITE.glob("team/*/index.html"))
    if not pages:
        pytest.skip("site not built")
    return pages


def _narrative(page: Path) -> str:
    m = re.search(r'<div class="narrative">(.*?)</div>', page.read_text(), re.S)
    if not m:
        return ""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split())


def test_a_club_with_a_written_story_gets_no_derived_one():
    """A generated summary under a real history is a worse page."""
    intruders = []
    for page in _pages():
        club_id = page.parent.name
        if (CONTENT / f"{club_id}.md").exists() and MARKER in page.read_text():
            intruders.append(club_id)
    assert not intruders, f"derived summary on a club with a written story: {intruders}"


def test_the_season_count_and_span_are_the_ones_in_the_database():
    conn = _conn()
    checked, wrong = 0, []
    for page in _pages():
        text = _narrative(page)
        if MARKER not in text:
            continue
        m = re.search(r"have (\d+) recorded seasons, (\d{4}/\d{2}) to (\d{4}/\d{2})", text)
        if not m:
            m2 = re.search(r"have (\d+) recorded seasons, (\d{4}/\d{2}),", text)
            if not m2:
                continue
            claimed, lo, hi = int(m2.group(1)), m2.group(2), m2.group(2)
        else:
            claimed, lo, hi = int(m.group(1)), m.group(2), m.group(3)
        checked += 1
        club_id = page.parent.name
        n, first, last = conn.execute(
            "SELECT COUNT(*), MIN(season_end_year), MAX(season_end_year)"
            " FROM standings WHERE club_id = ? AND position IS NOT NULL",
            (club_id,)).fetchone()
        want_lo = f"{first - 1}/{first % 100:02d}"
        want_hi = f"{last - 1}/{last % 100:02d}"
        if (claimed, lo, hi) != (n, want_lo, want_hi):
            wrong.append((club_id, (claimed, lo, hi), (n, want_lo, want_hi)))
    assert checked > 50, f"only checked {checked} pages - the parse is not matching"
    assert not wrong, f"claims that disagree with the database: {wrong[:5]}"


def test_it_never_prints_a_placeholder_division_name():
    """
    567 backfilled fifth-tier rows carry "Tier 5" as their division_name.
    That is a placeholder, not a competition, and a sentence repeating it
    reads as a bug.
    """
    offenders = []
    for page in _pages():
        text = _narrative(page)
        if MARKER in text and re.search(r"\bin Tier \d+ in \d{4}/\d{2}", text):
            offenders.append(page.parent.name)
    assert not offenders, f"placeholder division name in prose: {offenders[:5]}"


def test_a_club_with_almost_no_record_gets_no_invented_summary():
    """
    Under three recorded seasons there is nothing to summarise, and a
    sentence padded out of two rows would say more than the data does.
    Those keep the bare placeholder.
    """
    conn = _conn()
    wrong = []
    for page in _pages():
        club_id = page.parent.name
        n = conn.execute(
            "SELECT COUNT(*) FROM standings WHERE club_id = ? AND position IS NOT NULL",
            (club_id,)).fetchone()[0]
        if n < 3 and MARKER in page.read_text():
            wrong.append((club_id, n))
    assert not wrong, f"summary generated from too little record: {wrong}"
