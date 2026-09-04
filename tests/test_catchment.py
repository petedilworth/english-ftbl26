import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import catchment


# ── great_circle_miles ─────────────────────────────────────────────────
# Coordinates are club_master's own, and the expected distances are the
# ones the club pages already print. If this drifts, those pages are wrong.

GATESHEAD = (54.9622, -1.5677)
NEWCASTLE = (54.9756, -1.6217)
CARLISLE = (54.8955, -2.9174)
TRURO = (50.2635, -5.1210)


@pytest.mark.parametrize("a, b, expected", [
    (GATESHEAD, NEWCASTLE, 2.3),      # the closest pair never to have met
    (CARLISLE, NEWCASTLE, 51.7),      # Carlisle's nearest League neighbour
    (TRURO, GATESHEAD, 357.1),        # longest same-division pairing there is
])
def test_great_circle_matches_the_published_distances(a, b, expected):
    got = catchment.great_circle_miles(a[0], a[1], b[0], b[1])
    assert round(got, 1) == expected


def test_distance_is_symmetric_and_zero_to_itself():
    there = catchment.great_circle_miles(*GATESHEAD, *TRURO)
    back = catchment.great_circle_miles(*TRURO, *GATESHEAD)
    assert there == pytest.approx(back)
    assert catchment.great_circle_miles(*GATESHEAD, *GATESHEAD) == pytest.approx(0)


# ── attractiveness ─────────────────────────────────────────────────────

def test_a_bigger_club_pulls_harder():
    tiers = [1, 2, 3, 4, 5, 6]
    pulls = [catchment.attractiveness(t) for t in tiers]
    assert pulls == sorted(pulls, reverse=True)


def test_a_dead_club_pulls_on_nobody():
    # Tier 0 is a wound-up company. It cannot compete for a crowd, which
    # is exactly why the restored counterfactual exists.
    assert catchment.attractiveness(0) == 0.0


# ── the fixture ────────────────────────────────────────────────────────

def _db(clubs, msoas):
    """clubs: (club_id, current_tier, lat, lon, peak_tier or None)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_master (club_id TEXT, current_tier INT,"
                 " latitude REAL, longitude REAL)")
    conn.execute("CREATE TABLE standings (club_id TEXT, tier INT,"
                 " season_end_year INT)")
    for cid, tier, lat, lon, peak in clubs:
        conn.execute("INSERT INTO club_master VALUES (?,?,?,?)",
                     (cid, tier, lat, lon))
        if peak is not None:
            conn.execute("INSERT INTO standings VALUES (?,?,?)", (cid, peak, 2000))
    conn.execute(catchment.CREATE_MSOA_DEMOGRAPHICS_SQL)
    for code, lat, lon, pop, income in msoas:
        conn.execute(
            "INSERT INTO msoa_demographics (msoa_code, latitude, longitude,"
            " population, net_income) VALUES (?,?,?,?,?)",
            (code, lat, lon, pop, income))
    conn.commit()
    return conn


def _catchment(conn):
    catchment.rebuild_club_catchment(conn)
    return {r[0]: r for r in conn.execute(
        "SELECT club_id, catchment_pop_restored, voronoi_pop, contest_ratio,"
        " catchment_pop_current FROM club_catchment")}


def test_a_big_neighbour_takes_the_catchment():
    """
    The Bradford Park Avenue case, which is the whole reason the model is
    a gravity one rather than a radius. Park Avenue are 3.3 miles from
    Bradford City - a radius count would credit them with the whole city.
    """
    people = [(f"E{i:08d}", 53.78 + i * 0.001, -1.76, 5000, 30000)
              for i in range(20)]

    with_rival = _catchment(_db([
        ("park-avenue", 6, 53.7570, -1.7660, 3),
        ("bradford-city", 3, 53.8042, -1.7590, 3),
    ], people))

    alone = _catchment(_db([
        ("park-avenue", 6, 53.7570, -1.7660, 3),
    ], people))

    assert with_rival["park-avenue"][1] < alone["park-avenue"][1] * 0.6
    # And the contest measure should say so out loud.
    assert with_rival["park-avenue"][3] > 0.4
    assert alone["park-avenue"][3] == pytest.approx(0.0, abs=0.01)


def test_isolation_alone_earns_nothing():
    """
    The trap this module exists to avoid: a club with nobody near it must
    not outrank a contested club in a dense area, if the empty radius is
    genuinely empty. Distance says Workington; people say Maidstone.
    """
    remote = [("E00000001", 54.65, -3.55, 900, 26000)]          # thin moorland
    dense = [(f"E{i:08d}", 51.27 + i * 0.002, 0.52, 9000, 34000)
             for i in range(2, 12)]                             # commuter Kent

    got = _catchment(_db([
        ("workington", 6, 54.6420, -3.5580, 3),
        ("maidstone", 6, 51.2704, 0.5227, 4),
        ("gillingham", 4, 51.3840, 0.5600, 2),
    ], remote + dense))

    assert got["workington"][2] < got["maidstone"][2], (
        "the contested club should still have the larger natural hinterland")
    assert got["maidstone"][1] > got["workington"][1], (
        "ranking on people must not reduce to ranking on emptiness")


def test_a_dead_club_scores_nothing_now_but_something_restored():
    people = [(f"E{i:08d}", 53.50 + i * 0.002, -2.30, 6000, 28000)
              for i in range(10)]
    got = _catchment(_db([("bury", 0, 53.5100, -2.3170, 2)], people))
    assert got["bury"][4] == 0            # current: competes for nobody
    assert got["bury"][1] > 0             # restored: could command the town


def test_every_row_records_the_model_that_made_it():
    conn = _db([("a", 4, 53.0, -2.0, 3)],
               [("E00000001", 53.01, -2.0, 5000, 30000)])
    catchment.rebuild_club_catchment(conn)
    versions = {r[0] for r in conn.execute(
        "SELECT model_version FROM club_catchment")}
    assert versions == {catchment.MODEL_VERSION}


def test_no_msoas_leaves_the_table_empty_rather_than_wrong():
    conn = _db([("a", 4, 53.0, -2.0, 3)], [])
    assert catchment.rebuild_club_catchment(conn) == 0


# ── MSOA validation ────────────────────────────────────────────────────

@pytest.mark.parametrize("row, expect", [
    ({"latitude": 53.0, "longitude": -2.0, "population": 5000}, []),
    ({"latitude": 40.0, "longitude": -2.0, "population": 5000}, ["latitude"]),
    ({"latitude": 53.0, "longitude": 12.0, "population": 5000}, ["longitude"]),
    ({"latitude": 53.0, "longitude": -2.0, "population": 0}, ["population"]),
    ({"latitude": None, "longitude": None, "population": 5000}, ["centroid"]),
])
def test_msoa_validation_rejects_what_would_mislead(row, expect):
    problems = " ".join(catchment._validate_msoa(row))
    for token in expect:
        assert token in problems
    if not expect:
        assert not problems


def test_income_outside_its_own_interval_is_rejected():
    problems = catchment._validate_msoa({
        "latitude": 53.0, "longitude": -2.0, "population": 5000,
        "net_income": 40000, "income_ci_lower": 20000, "income_ci_upper": 30000,
    })
    assert any("confidence interval" in p for p in problems)


# ── the site render ────────────────────────────────────────────────────
# These use the shared fixture database, the same as tests/test_site_build.py.

sys.path.insert(0, str(Path(__file__).parent))


def _site_db(tmp_path, catchment_rows):
    from test_digest import _make_db
    mem = _make_db()
    path = tmp_path / "test.db"
    disk = sqlite3.connect(path)
    mem.backup(disk)
    disk.execute(catchment.CREATE_CLUB_CATCHMENT_SQL)
    disk.executemany(
        "INSERT INTO club_catchment (club_id, catchment_pop_current,"
        " catchment_pop_restored, catchment_income, contest_ratio,"
        " nearest_rival_id, nearest_rival_miles, model_version)"
        " VALUES (?,?,?,?,?,?,?,?)",
        # The current figure defaults to the restored one, which is what
        # a club at its ceiling looks like. Rows that want the two to
        # differ pass eight values instead of seven.
        [r if len(r) == 8 else (r[0], r[1]) + r[1:] for r in catchment_rows],
    )
    disk.commit()
    disk.close()
    return path


def test_catchment_pages_render_when_there_is_data(tmp_path):
    from site_build import SiteBuilder
    db = _site_db(tmp_path, [
        ("giant-fc", 900_000, 34_000, 0.12, "steady-fc", 8.4, "test"),
        ("steady-fc", 140_000, 27_000, 0.71, "giant-fc", 8.4, "test"),
    ])
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()

    page = out / "insights" / "catchment" / "index.html"
    assert page.exists()
    assert "900,000" in page.read_text()


def test_catchment_pages_are_absent_when_the_table_is_empty(tmp_path):
    """
    The demographics CSV cannot be fetched in every environment, so an
    empty club_catchment must take the metric off the chip row entirely
    rather than publishing a blank chart with a confident heading.
    """
    from site_build import SiteBuilder
    db = _site_db(tmp_path, [])
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()

    assert not (out / "insights" / "catchment" / "index.html").exists()
    index = (out / "insights" / "index.html").read_text()
    assert "Catchment population" not in index


def test_contested_share_is_plotted_as_a_percentage(tmp_path):
    from site_build import SiteBuilder
    db = _site_db(tmp_path, [
        ("giant-fc", 900_000, 34_000, 0.12, "steady-fc", 8.4, "test"),
        ("steady-fc", 140_000, 27_000, 0.71, "giant-fc", 8.4, "test"),
    ])
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()
    page = (out / "insights" / "catchment" / "contested" / "index.html").read_text()
    assert "71%" in page


# ── the current_tier convention ────────────────────────────────────────

def test_every_tier_in_club_master_has_an_explicit_pull_weight():
    """
    club_master.current_tier feeds the gravity model. A value with no
    entry in TIER_ATTRACTIVENESS silently falls back to the default,
    which would give a step-6 club the same pull as a step-3 one.
    """
    import sqlite3
    db = Path(__file__).parent.parent / "data" / "db" / "england.db"
    if not db.exists():
        pytest.skip("no built database")
    tiers = {t for (t,) in sqlite3.connect(db).execute(
        "SELECT DISTINCT current_tier FROM club_master WHERE current_tier IS NOT NULL")}
    missing = sorted(t for t in tiers if t not in catchment.TIER_ATTRACTIVENESS)
    assert not missing, f"tiers with no explicit weight: {missing}"


def test_a_club_whose_successor_plays_is_not_flagged_as_exerting_no_pull():
    """
    current_tier = 0 means nobody plays under this id anywhere, and the
    model gives that club's town to its neighbours. If the prospect
    research has established a successor's ceiling, somebody is playing,
    and a 0 would hand away a town that is not free.
    """
    import csv, sqlite3
    root = Path(__file__).parent.parent
    prospects_csv, db = root / "club_prospects.csv", root / "data" / "db" / "england.db"
    if not (prospects_csv.exists() and db.exists()):
        pytest.skip("needs club_prospects.csv and a built database")
    conn = sqlite3.connect(db)
    wrong = []
    for row in csv.DictReader(prospects_csv.open(encoding="utf-8")):
        if not (row.get("successor_peak_tier") or "").strip():
            continue
        got = conn.execute("SELECT current_tier FROM club_master WHERE club_id=?",
                           (row["club_id"],)).fetchone()
        if got and got[0] == 0:
            wrong.append(row["club_id"])
    assert not wrong, f"successor plays but current_tier is 0: {wrong}"


# ── the club panel and the method page ─────────────────────────────────

def _built(tmp_path, rows):
    from site_build import SiteBuilder
    out = tmp_path / "site"
    SiteBuilder(_site_db(tmp_path, rows), out, charts_enabled=False).build()
    return out


CEILING = ("giant-fc", 900_000, 34_000, 0.12, "steady-fc", 8.4, "test")
FALLEN = ("steady-fc", 140_000, 900_000, 27_000, 0.71, "giant-fc", 8.4, "test")


def test_a_club_page_carries_its_catchment(tmp_path):
    page = (_built(tmp_path, [CEILING, FALLEN])
            / "team" / "giant-fc" / "index.html").read_text()
    assert "Catchment" in page
    assert "900,000" in page
    assert "12%" in page
    assert "8.4 miles" in page


def test_a_club_with_no_catchment_row_gets_no_panel(tmp_path):
    """
    The same rule the finance panel follows: a club the model cannot see
    gets a shorter page, not a table of dashes.
    """
    page = (_built(tmp_path, [CEILING])
            / "team" / "steady-fc" / "index.html").read_text()
    assert "<h2>Catchment</h2>" not in page


def test_the_restored_figure_appears_only_where_it_differs(tmp_path):
    """
    Two identical numbers side by side read as a mistake. A club at its
    ceiling shows one; a fallen club shows what returning would be worth.
    """
    out = _built(tmp_path, [CEILING, FALLEN])
    at_ceiling = (out / "team" / "giant-fc" / "index.html").read_text()
    fallen = (out / "team" / "steady-fc" / "index.html").read_text()
    assert "restored to its ceiling" not in at_ceiling
    assert "restored to its ceiling" in fallen
    assert "140,000" in fallen and "900,000" in fallen


def test_the_method_page_states_the_weights_the_model_actually_uses(tmp_path):
    """
    Read from catchment.TIER_ATTRACTIVENESS rather than written down, so
    the page cannot describe a model the pipeline is not running.
    """
    page = (_built(tmp_path, [CEILING, FALLEN])
            / "insights" / "catchment" / "method" / "index.html")
    assert page.exists()
    text = page.read_text()
    for weight in catchment.TIER_ATTRACTIVENESS.values():
        assert f"{weight:g}" in text
    assert catchment.MODEL_VERSION in text
    assert f"β = {catchment.BETA:g}" in text


def test_the_method_page_is_skipped_without_its_prose(tmp_path, monkeypatch):
    """
    The same gate points-eras uses: a page whose argument is missing is
    not published as tables alone. Three numbers that need explaining
    least of all deserve a page of tables with no explanation.
    """
    from test_site_build import _build_site_with_content
    out = _build_site_with_content(
        tmp_path, monkeypatch, _site_db(tmp_path, [CEILING]), {})
    assert not (out / "insights" / "catchment" / "method" / "index.html").exists()


@pytest.mark.parametrize("miles, approximate, expected", [
    (8.42, False, "8.4 miles"),
    (43.65, False, "43.6 miles"),
    (2.26, True, "~2 miles"),
    # Bury to Radcliffe on town-placed coordinates. Stainton Park is about
    # three miles from Gigg Lane, so a decimal place here would be a
    # precision the placement does not have.
    (0.5, True, "a mile or two"),
    (1.4, True, "a mile or two"),
    (None, False, None),
])
def test_a_distance_is_said_to_the_precision_it_has(miles, approximate, expected):
    from site_build import _distance_phrase
    assert _distance_phrase(miles, approximate) == expected


# ── the cells behind the contested figure ──────────────────────────────

def _db_conn():
    import pytest
    db = Path(__file__).parent.parent / "data" / "db" / "england.db"
    if not db.exists():
        pytest.skip("no built database")
    return sqlite3.connect(db)


def test_every_area_belongs_to_exactly_one_club():
    """
    A Voronoi assignment is a partition: each area has one nearest club.
    Two rows for one area would double-count its people in the contested
    figure, and none would lose them.
    """
    conn = _db_conn()
    total, distinct = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT msoa_code) FROM msoa_assignment").fetchone()
    assert total == distinct, "an area is assigned to more than one club"
    areas = conn.execute("SELECT COUNT(*) FROM msoa_demographics").fetchone()[0]
    assert total == areas, f"{areas - total} areas have no nearest club"


def test_the_cells_reproduce_the_contested_figure():
    """
    The number and the picture come from the same arrays and must agree.
    contest_ratio says what share of the people nearest a club it loses;
    summing kept_share over that club's own areas, weighted by
    population, has to give the same answer - otherwise the map is
    illustrating something the page does not claim.
    """
    conn = _db_conn()
    rows = conn.execute(
        "SELECT a.club_id,"
        " 1.0 - SUM(a.kept_share * m.population) / SUM(m.population),"
        " cc.contest_ratio"
        " FROM msoa_assignment a"
        " JOIN msoa_demographics m ON m.msoa_code = a.msoa_code"
        " JOIN club_catchment cc ON cc.club_id = a.club_id"
        " GROUP BY a.club_id").fetchall()
    assert len(rows) > 100, "too few clubs compared"
    # contest_ratio is stored rounded to four places.
    wrong = [(cid, d, s) for cid, d, s in rows
             if s is not None and abs(d - s) > 5e-5]
    assert not wrong, f"cells disagree with contest_ratio: {wrong[:5]}"


def test_a_kept_share_is_a_share():
    conn = _db_conn()
    bad = conn.execute(
        "SELECT COUNT(*) FROM msoa_assignment"
        " WHERE kept_share < 0 OR kept_share > 1").fetchone()[0]
    assert bad == 0, f"{bad} areas have a kept_share outside 0..1"


def test_the_map_payload_points_every_cell_at_a_real_club():
    """
    Cells carry an index into the clubs array rather than a club_id, to
    keep 6,829 repeated strings out of the payload. An index that does
    not resolve would draw a dot in nobody's colour.
    """
    import json
    import pytest
    data_file = (Path(__file__).parent.parent / "site" / "map" / "map-data.js")
    if not data_file.exists():
        pytest.skip("site not built")
    raw = data_file.read_text()
    payload = json.loads(raw[raw.index("=") + 1:].rstrip().rstrip(";"))
    cells = payload.get("cells") or []
    assert cells, "no catchment cells in the map payload"
    n = len(payload["clubs"])
    assert all(0 <= c[2] < n for c in cells), "a cell points outside the clubs array"
    assert all(0.0 <= c[3] <= 1.0 for c in cells), "a cell's kept share is not a share"
