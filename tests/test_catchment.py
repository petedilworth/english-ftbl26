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
        "INSERT INTO club_catchment (club_id, catchment_pop_restored,"
        " catchment_income, contest_ratio, nearest_rival_id,"
        " nearest_rival_miles, model_version) VALUES (?,?,?,?,?,?,?)",
        catchment_rows,
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
