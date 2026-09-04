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


# ── the all-time columns, checked against the standings they came from ─

CSV = PROJECT_ROOT / "site" / "teams" / "table" / "clubs.csv"


def _csv_rows():
    if not CSV.exists():
        pytest.skip("site not built")
    import csv
    with CSV.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_the_career_columns_match_the_standings_they_are_summed_from():
    if not DB.exists():
        pytest.skip("no built database")
    conn = sqlite3.connect(DB)
    truth = {r[0]: r[1:] for r in conn.execute(
        "SELECT club_id, COUNT(*), SUM(status = 'Champions'), SUM(played),"
        " SUM(won), SUM(gf), SUM(ga), SUM(COALESCE(points_deducted, 0))"
        " FROM standings WHERE club_id IS NOT NULL GROUP BY 1")}

    checked = 0
    for row in _csv_rows():
        seasons, titles, played, won, gf, ga, docked = truth[row["club_id"]]
        assert int(row["Seasons"]) == seasons
        assert int(row["Titles"]) == titles
        assert int(row["Played"] or 0) == (played or 0)
        assert int(row["Goals for"] or 0) == (gf or 0)
        assert int(row["Goals against"] or 0) == (ga or 0)
        assert int(row["Goal difference"] or 0) == (gf or 0) - (ga or 0)
        # Blank rather than nought where a club was never docked: a zero
        # would sort it among the clubs that were.
        assert int(row["Points docked"] or 0) == docked
        checked += 1
    assert checked == len(truth)


def test_best_is_never_worse_than_average_and_average_never_worse_than_worst():
    for row in _csv_rows():
        best, average, worst = (float(row["Best finish"]),
                                float(row["Average finish"]),
                                float(row["Worst finish"]))
        assert best <= average <= worst, row["club_id"]


def test_the_csv_is_one_row_per_club_and_leads_with_the_id():
    """
    A display name is not a key. Anything joined against this file wants
    the permanent id, and "Manchester United" is not it.
    """
    rows = _csv_rows()
    ids = [row["club_id"] for row in rows]
    assert all(ids), "a row has no club_id"
    assert len(ids) == len(set(ids))

    if DB.exists():
        conn = sqlite3.connect(DB)
        assert set(ids) == {r[0] for r in conn.execute(
            "SELECT DISTINCT club_id FROM standings WHERE club_id IS NOT NULL")}


def test_the_csv_holds_sort_values_rather_than_formatted_ones():
    """
    "£1.2m" is for reading and 1200000 is for computing with. A CSV is
    for computing with.
    """
    for row in _csv_rows():
        for column in ("Turnover", "Wages", "Catchment", "Contested"):
            if row[column]:
                float(row[column])
                assert "£" not in row[column] and "%" not in row[column]


def test_an_unrecorded_value_is_an_empty_field_not_a_zero():
    rows = _csv_rows()
    sparse = [row["Pitch"] for row in rows]
    assert any(v == "" for v in sparse), "expected a mostly-empty column"
    assert all(v != "0" for v in sparse)


def test_the_csv_and_the_table_carry_the_same_columns():
    html = _page()
    labels = re.findall(r'<th[^>]*data-key="[^"]+"[^>]*>(.*?)</th>', html, re.S)
    labels = [re.sub(r"<[^>]+>", "", x).strip() for x in labels]
    labels = labels[:len(labels) // 2]          # the header repeats per table
    header = _csv_rows()[0].keys()
    # club_id leads the file and has no column in the table.
    assert list(header)[1:] == labels


# ── "now" has to mean now ──────────────────────────────────────────────

SITE = PROJECT_ROOT / "site"


def _dormant_clubs(conn):
    """Clubs whose data has stopped: last recorded season is not the latest."""
    latest = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    return {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT club_id, canonical_name, last_season_in_db FROM club_trajectory"
        " WHERE last_season_in_db <> ?", (latest,))}


def test_no_club_that_stopped_playing_is_listed_under_now():
    """
    club_trajectory.current_tier is the tier of a club's LAST recorded
    season, and 189 of 305 clubs here have data that has stopped. Printed
    under a column headed "Now" that is a false present tense, and it was
    one: Wimbledon FC, dissolved in 2004, was listed among clubs that now
    play in the top two divisions.

    The excluded clubs belong in the note, not in the table, so this checks
    the table rows only.
    """
    page = SITE / "insights" / "fallen-giants" / "index.html"
    if not page.exists() or not DB.exists():
        pytest.skip("site not built")
    conn = sqlite3.connect(DB)
    dormant = _dormant_clubs(conn)

    html = page.read_text()
    body = html.split("<tbody>", 1)[-1] if "<tbody>" in html else html
    listed = set(re.findall(r'/team/([a-z0-9-]+)/', body))
    wrong = sorted(dormant[c][0] for c in listed & set(dormant))
    assert not wrong, f"listed under 'Now' but no longer playing: {wrong}"


def test_a_club_whose_data_stopped_does_not_claim_a_current_level():
    """
    The same claim on 189 club pages. Wimbledon FC's read "Current level:
    Tier 2" twenty-two years after they were dissolved. The tagline already
    carries the span; the stat card has to stop asserting the present.
    """
    if not DB.exists():
        pytest.skip("no built database")
    conn = sqlite3.connect(DB)
    dormant = _dormant_clubs(conn)

    checked, wrong = 0, []
    for club_id, (name, _last) in dormant.items():
        page = SITE / "team" / club_id / "index.html"
        if not page.exists():
            continue
        checked += 1
        if "Current level" in page.read_text():
            wrong.append(name)
    if not checked:
        pytest.skip("site not built")
    assert not wrong, f"no longer playing but page says 'Current level': {wrong}"


# ── the sort is in the URL, so the key has to be stable and unique ──────

def test_every_sortable_column_has_a_unique_key():
    """
    The shareable sort is #sort=<data-key>,<direction>, keyed on the
    column's data-key rather than its index so a link survives a column
    being added or moved. That only works if the key is unique: two
    columns sharing one would make a link ambiguous, and the restore
    would silently pick whichever came first.
    """
    page = _page()
    keys = re.findall(r'<th[^>]*data-key="([^"]+)"', page)
    assert keys, "no sortable columns found"
    duplicates = sorted({k for k in keys if keys.count(k) > len(keys) // len(set(keys))})
    counts = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    # Two tables on the page means each key appears once per table.
    per_table = max(counts.values())
    odd = [k for k, n in counts.items() if n != per_table]
    assert not odd, f"columns appearing a different number of times: {odd}"


def test_the_sort_state_is_written_to_the_url():
    """
    Seventy-four columns and, before this, no way to say "look at this":
    the order lived only in the DOM, so an interesting view died with the
    tab it was found in.
    """
    js = (PROJECT_ROOT / "static" / "club-table.js").read_text()
    assert "#sort=" in js, "the sort is not encoded in the hash"
    assert "replaceState" in js, (
        "sorting should replace the history entry, not stack one per click")
    assert "hashchange" in js, "a pasted link must apply without a reload"
