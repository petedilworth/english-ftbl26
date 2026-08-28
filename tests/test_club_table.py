"""
The all-clubs table: every club with a record, every column the data
supports, sortable on any of them.
"""
import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

PROJECT_ROOT = Path(__file__).parent.parent
DB = PROJECT_ROOT / "data" / "db" / "england.db"
PAGE = PROJECT_ROOT / "site" / "teams" / "table" / "index.html"


def _page():
    if not PAGE.exists():
        pytest.skip("site not built")
    return PAGE.read_text()


def _bodies(html):
    return re.findall(r"<tbody>(.*?)</tbody>", html, re.S)


def _rows(body):
    return re.findall(r"<tr>(.*?)</tr>", body, re.S)


def _cells(row):
    return re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)


def test_every_club_with_a_record_appears_exactly_once():
    """
    Two tables, and a club belongs to one of them. Appearing in both
    would double it in any count made from the page; appearing in
    neither would lose it.
    """
    if not DB.exists():
        pytest.skip("no built database")
    html = _page()
    ids = re.findall(r'href="[^"]*/team/([a-z0-9-]+)/"', html)
    # The nearest-club column links too, so count only the first cell of
    # each row.
    first = []
    for body in _bodies(html):
        for row in _rows(body):
            cell = _cells(row)[0]
            match = re.search(r'/team/([a-z0-9-]+)/', cell)
            if match:
                first.append(match.group(1))

    conn = sqlite3.connect(DB)
    expected = {r[0] for r in conn.execute(
        "SELECT DISTINCT club_id FROM standings WHERE club_id IS NOT NULL")}
    assert len(first) == len(set(first)), "a club appears twice"
    assert set(first) == expected
    assert ids  # the nearest-club links are there too


def test_the_two_tables_split_on_the_last_complete_season():
    if not DB.exists():
        pytest.skip("no built database")
    html = _page()
    bodies = _bodies(html)
    assert len(bodies) == 2

    conn = sqlite3.connect(DB)
    season = conn.execute(
        "SELECT MAX(season_end_year) FROM standings WHERE tier = 1").fetchone()[0]
    current = conn.execute(
        "SELECT COUNT(DISTINCT club_id) FROM standings"
        " WHERE season_end_year = ?", (season,)).fetchone()[0]
    assert len(_rows(bodies[0])) == current


def test_a_missing_value_is_blank_and_carries_no_sort_key():
    """
    The rule the whole page turns on. Ground ownership is known for eighty
    clubs of three hundred; if a blank sorted as zero, "smallest capacity"
    would list every unresearched club first and the table would be lying.
    """
    html = _page()
    empty = re.findall(r"<td[^>]*>\s*</td>", html)
    assert empty, "expected some columns to be unrecorded"
    for cell in empty:
        assert "data-sort" not in cell


def test_every_sort_key_on_a_numeric_column_is_a_number():
    """
    The script reads data-sort rather than the cell text, so it never has
    to turn "£1.2m" or "38%" back into a number - but only if the value
    put there really is one.
    """
    html = _page()
    for cell in re.findall(r'<td class="num"[^>]*data-sort="([^"]*)"', html):
        float(cell)


def test_the_per_tier_columns_add_up_to_the_clubs_recorded_window():
    """
    The eight tier columns come from one JSON blob and are the only place
    a zero is shown rather than a blank - a club really did play no
    seasons at that level. They must total the window the club's natural
    level was computed over, or one of them is being dropped.
    """
    if not DB.exists():
        pytest.skip("no built database")
    html = _page()
    keys = re.findall(r'<th[^>]*data-key="([^"]+)"', html)
    keys = keys[:len(keys) // 2]          # the header repeats per table
    tier_columns = [keys.index(k) for k in
                    ("t1", "t2", "t3", "t4", "t5", "t6", "t7", "tout")]

    conn = sqlite3.connect(DB)
    windows = dict(conn.execute(
        "SELECT club_id, natural_level_seasons FROM club_trajectory"))

    checked = 0
    for body in _bodies(html):
        for row in _rows(body):
            cells = _cells(row)
            match = re.search(r'/team/([a-z0-9-]+)/', cells[0])
            if not match:
                continue
            window = windows.get(match.group(1))
            if not window:
                continue
            total = sum(int(re.sub(r"<[^>]+>", "", cells[i]).strip() or 0)
                        for i in tier_columns)
            assert total == window, match.group(1)
            checked += 1
    assert checked > 100


def test_the_accounts_column_is_named_for_the_season_it_holds():
    """
    Clubs file months after a season ends, so the newest accounts are not
    the newest season played. Asking club_finances for the complete season
    returns nothing, which is how Arsenal first came out with five blank
    columns.
    """
    if not DB.exists():
        pytest.skip("no built database")
    html = _page()
    conn = sqlite3.connect(DB)
    season = conn.execute(
        "SELECT MAX(season_end_year) FROM club_finances"
        " WHERE disclosure = 'full'").fetchone()[0]
    label = f"{season - 1}/{str(season)[2:]}"
    assert f"{label} accounts" in html


def test_the_sort_script_is_loaded():
    assert "club-table.js" in _page()
