import csv
import logging
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import catchment
import roster

PROJECT_ROOT = Path(__file__).parent.parent


# ── slugify ────────────────────────────────────────────────────────────
# A hand-written club id is permanent and a typo in one is invisible, so
# every id has to be checkable against the name it came from.

@pytest.mark.parametrize("name, expected", [
    ("Chelmsford City", "chelmsford-city"),
    ("Hampton & Richmond Borough", "hampton-and-richmond-borough"),
    ("King's Lynn Town", "kings-lynn-town"),
    ("Weston-super-Mare", "weston-super-mare"),
    ("  AFC Totton  ", "afc-totton"),
])
def test_slugify(name, expected):
    assert roster.slugify(name) == expected


def test_slugify_matches_the_ids_club_master_already_uses():
    """
    The roster mints ids in the same shape as the spine it sits beside.
    Every club_master id should still begin with its own club's slug -
    the suffix a club uses is its own, but the name in front of it is
    not negotiable.
    """
    path = PROJECT_ROOT / "club_master.csv"
    if not path.exists():
        pytest.skip("no club_master.csv")
    bad = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            cid, name = row["club_id"].strip(), row["canonical_name"].strip()
            # One licensed variation, and club_master uses it once: a
            # leading AFC may move to the end, so AFC Fylde is fylde-afc.
            allowed = {roster.slugify(name)}
            if name.lower().startswith("afc "):
                allowed.add(roster.slugify(name[4:] + " AFC"))
            if not any(cid.startswith(a) for a in allowed):
                bad.append((cid, name))
    assert not bad, f"ids that do not match their name: {bad}"


# ── the fixture ────────────────────────────────────────────────────────

HEADER = ("club_id,canonical_name,tier,division,ground_name,latitude,longitude,"
          "location_precision,locality,source_url,notes\n")

GOOD = ("chelmsford-city-fc,Chelmsford City,6,National League South,Melbourne"
        " Stadium,51.7300,0.4700,town,Chelmsford,https://example.org/a,\n")


def _db(master=()):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_master (club_id TEXT PRIMARY KEY,"
                 " current_tier INT, latitude REAL, longitude REAL)")
    for cid in master:
        conn.execute("INSERT INTO club_master VALUES (?,?,?,?)",
                     (cid, 6, 51.5, 0.1))
    conn.commit()
    return conn


def _csv(tmp_path, body, header=HEADER):
    path = tmp_path / "club_roster.csv"
    path.write_text(header + body, encoding="utf-8")
    return path


def _seed(tmp_path, body, master=(), header=HEADER):
    conn = _db(master)
    n = roster.seed_club_roster(conn, _csv(tmp_path, body, header))
    return conn, n


# ── loading ────────────────────────────────────────────────────────────

def test_a_good_row_loads(tmp_path):
    conn, n = _seed(tmp_path, GOOD)
    assert n == 1
    row = conn.execute("SELECT club_id, canonical_name, tier, latitude,"
                       " location_precision FROM club_roster").fetchone()
    assert row == ("chelmsford-city-fc", "Chelmsford City", 6, 51.73, "town")


def test_a_missing_file_is_not_an_error(tmp_path):
    conn = _db()
    assert roster.seed_club_roster(conn, tmp_path / "nope.csv") == 0


def test_a_missing_required_column_is_an_error(tmp_path):
    conn = _db()
    with pytest.raises(ValueError, match="missing columns"):
        roster.seed_club_roster(
            conn, _csv(tmp_path, "chelmsford-city-fc,Chelmsford City,6\n",
                       header="club_id,canonical_name,tier\n"))


def test_rows_that_have_left_the_csv_are_removed(tmp_path):
    conn, _ = _seed(tmp_path, GOOD)
    roster.seed_club_roster(conn, _csv(tmp_path, ""))
    assert conn.execute("SELECT COUNT(*) FROM club_roster").fetchone()[0] == 0


# ── the rejections ─────────────────────────────────────────────────────

def test_a_club_already_in_club_master_is_refused(tmp_path, caplog):
    """
    The one that must never be a warning in the data. A club in both
    files is two clubs to the gravity model: it competes with itself and
    each copy takes roughly half the share the real club should have.
    """
    with caplog.at_level(logging.WARNING):
        conn, n = _seed(tmp_path, GOOD, master=["chelmsford-city-fc"])
    assert n == 0
    assert "counted twice" in caplog.text


def test_a_tier_with_no_pull_weight_is_refused(tmp_path):
    """
    Falling through to DEFAULT_ATTRACTIVENESS would give a step-6 club
    the same pull as a step-3 one, and nothing would say so.
    """
    body = GOOD.replace(",6,National", ",99,National")
    _, n = _seed(tmp_path, body)
    assert n == 0
    # And the tiers the roster actually uses do have weights.
    assert {6, 7} <= set(catchment.TIER_ATTRACTIVENESS)


@pytest.mark.parametrize("lat, lon", [
    ("58.9000", "0.4700"),      # Scotland
    ("51.7300", "9.4700"),      # Germany
    ("", "0.4700"),             # missing
])
def test_a_coordinate_outside_england_is_refused(tmp_path, lat, lon):
    body = GOOD.replace(",51.7300,0.4700,", f",{lat},{lon},")
    _, n = _seed(tmp_path, body)
    assert n == 0


def test_an_unknown_precision_is_refused(tmp_path):
    _, n = _seed(tmp_path, GOOD.replace(",town,", ",approximate,"))
    assert n == 0


def test_an_id_that_does_not_match_its_name_is_refused(tmp_path):
    """A typo in a hand-written id is permanent, so it is caught on load."""
    _, n = _seed(tmp_path, GOOD.replace("chelmsford-city-fc,Chelmsford City",
                                        "chlemsford-city-fc,Chelmsford City"))
    assert n == 0


def test_a_duplicate_id_within_the_csv_is_refused(tmp_path):
    _, n = _seed(tmp_path, GOOD + GOOD)
    assert n == 1


# ── what it does to the model ──────────────────────────────────────────

def _catchment_db(master_clubs, roster_clubs, msoas):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_master (club_id TEXT PRIMARY KEY,"
                 " current_tier INT, latitude REAL, longitude REAL)")
    conn.execute("CREATE TABLE standings (club_id TEXT, tier INT,"
                 " season_end_year INT)")
    for cid, tier, lat, lon, peak in master_clubs:
        conn.execute("INSERT INTO club_master VALUES (?,?,?,?)",
                     (cid, tier, lat, lon))
        conn.execute("INSERT INTO standings VALUES (?,?,?)", (cid, peak, 2000))
    conn.execute(roster.CREATE_CLUB_ROSTER_SQL)
    for cid, tier, lat, lon in roster_clubs:
        conn.execute(
            "INSERT INTO club_roster (club_id, canonical_name, tier, latitude,"
            " longitude, location_precision) VALUES (?,?,?,?,?,'town')",
            (cid, cid, tier, lat, lon))
    conn.execute(catchment.CREATE_MSOA_DEMOGRAPHICS_SQL)
    for code, lat, lon, pop in msoas:
        conn.execute(
            "INSERT INTO msoa_demographics (msoa_code, latitude, longitude,"
            " population, net_income) VALUES (?,?,?,?,30000)",
            (code, lat, lon, pop))
    conn.commit()
    catchment.rebuild_club_catchment(conn)
    return {r[0]: r[1:] for r in conn.execute(
        "SELECT club_id, catchment_pop_restored, contest_ratio FROM club_catchment")}


PEOPLE = [(f"E{i:08d}", 53.60 + i * 0.004, -2.60, 5000) for i in range(20)]
FALLEN = ("fallen-fc", 6, 53.6400, -2.6000, 3)


def test_a_roster_neighbour_takes_share_the_model_could_not_see():
    """
    The reason the roster exists. Before it, a club that had never
    reached the fifth tier was invisible, so a fallen club's town looked
    empty of competition and its catchment was flattered.
    """
    alone = _catchment_db([FALLEN], [], PEOPLE)
    contested = _catchment_db([FALLEN], [("neighbour-fc", 6, 53.6600, -2.6000)],
                              PEOPLE)
    assert contested["fallen-fc"][0] < alone["fallen-fc"][0]
    assert contested["fallen-fc"][1] > alone["fallen-fc"][1]


def test_a_roster_club_gets_its_own_catchment_row():
    got = _catchment_db([FALLEN], [("neighbour-fc", 6, 53.6600, -2.6000)], PEOPLE)
    assert got["neighbour-fc"][0] > 0


def test_a_roster_club_is_not_restored_to_a_ceiling_it_never_had():
    """
    A roster club's ceiling is its current tier by construction: anything
    that had reached the fifth tier would be in club_master with the
    standings to prove it. So the counterfactual must leave it where it
    is, or a step-3 club would be credited with a promotion it never had.
    """
    weak = _catchment_db([FALLEN], [("neighbour-fc", 7, 53.6600, -2.6000)], PEOPLE)
    strong = _catchment_db([FALLEN], [("neighbour-fc", 6, 53.6600, -2.6000)], PEOPLE)
    assert weak["neighbour-fc"][0] < strong["neighbour-fc"][0]


# ── the shipped file ───────────────────────────────────────────────────

def test_the_shipped_roster_loads_cleanly_if_it_exists(caplog):
    """
    Every row in the committed file must survive validation. A skipped
    row is a club the model cannot see, which is the bug the roster was
    written to fix.
    """
    path = PROJECT_ROOT / "club_roster.csv"
    if not path.exists():
        pytest.skip("no club_roster.csv yet")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        expected = sum(1 for row in csv.DictReader(fh) if row.get("club_id", "").strip())
    conn = sqlite3.connect(PROJECT_ROOT / "data" / "db" / "england.db") \
        if (PROJECT_ROOT / "data" / "db" / "england.db").exists() else None
    if conn is None:
        pytest.skip("no built database")
    master = {r[0] for r in conn.execute("SELECT club_id FROM club_master")}
    mem = _db(master)
    with caplog.at_level(logging.WARNING):
        loaded = roster.seed_club_roster(mem, path)
    assert loaded == expected, caplog.text


# ── the shipped data against the FA's own allocations ──────────────────

ALLOCATIONS = PROJECT_ROOT / "data" / "raw" / "nls-allocations-2026-27.tsv"


def _allocations():
    if not ALLOCATIONS.exists():
        pytest.skip("no allocations file")
    rows = []
    with ALLOCATIONS.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("division\t"):
                continue
            division, tier, rank, name = line.rstrip("\n").split("\t")
            rows.append((division, int(tier), int(rank), name))
    return rows


def test_the_allocations_hold_every_division_at_its_real_size():
    """
    The parse is geometric - column bands and heights on a page - so the
    thing that proves it worked is that each division comes out the size
    it actually is. A lost row is a town handed to a neighbour.
    """
    sizes = {}
    for division, _, _, _ in _allocations():
        sizes[division] = sizes.get(division, 0) + 1
    assert sizes == {
        "National League": 24,
        "National League North": 24,
        "National League South": 24,
        "Isthmian League Premier": 22,
        "Northern Premier League Premier": 22,
        "Southern League Premier Central": 22,
        "Southern League Premier South": 22,
    }


def test_the_fifth_tier_in_the_allocations_matches_this_repos_own_standings():
    """
    An independent check on the whole extraction. The FA's step 1 column
    and this site's in-progress fifth-tier season are two unrelated
    sources for the same 24 clubs, and every name has to resolve.
    """
    db = PROJECT_ROOT / "data" / "db" / "england.db"
    if not db.exists():
        pytest.skip("no built database")
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    import entities
    conn = sqlite3.connect(db)
    resolver = entities.build_resolver(conn)

    season = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    from_db = {r[0] for r in conn.execute(
        "SELECT DISTINCT club_id FROM standings WHERE tier = 5"
        " AND season_end_year = ?", (season,))}
    from_pdf = {resolver.get(entities._normalize(name))
                for _, tier, _, name in _allocations() if tier == 5}
    assert None not in from_pdf, "a fifth-tier name did not resolve"
    assert from_pdf == from_db


def test_no_club_is_in_both_the_master_and_the_roster():
    """
    Belt and braces around seed_club_roster's own refusal: a club in both
    files competes with itself and each copy takes half its share.
    """
    if not (PROJECT_ROOT / "club_roster.csv").exists():
        pytest.skip("no club_roster.csv")
    def ids(name):
        with (PROJECT_ROOT / name).open(encoding="utf-8-sig", newline="") as fh:
            return {r["club_id"].strip() for r in csv.DictReader(fh)}
    assert not (ids("club_master.csv") & ids("club_roster.csv"))


def test_every_club_the_allocations_name_is_recorded_at_that_tier():
    """
    The FA says where each club plays, and current_tier is what the
    gravity model reads as its pull. The two must not drift apart, in
    either file.
    """
    db = PROJECT_ROOT / "data" / "db" / "england.db"
    if not db.exists():
        pytest.skip("no built database")
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    import entities
    conn = sqlite3.connect(db)
    resolver = entities.build_resolver(conn)
    master = dict(conn.execute("SELECT club_id, current_tier FROM club_master"))
    try:
        roster_tiers = dict(conn.execute("SELECT club_id, tier FROM club_roster"))
    except sqlite3.Error:
        roster_tiers = {}

    # Clubs the ONS gazetteer cannot place, because their local authority
    # is a wide rural one whose centroid stands in for no town at all.
    # They are reported rather than guessed - see docs/roster-data.md -
    # but the count is pinned here so that it cannot grow unnoticed.
    UNPLACEABLE = 20

    wrong, unplaced = [], []
    for _, tier, _, name in _allocations():
        club_id = resolver.get(entities._normalize(name))
        if club_id:
            if master.get(club_id) != tier:
                wrong.append((name, club_id, master.get(club_id), tier))
            continue
        rostered = roster_tiers.get(f"{roster.slugify(name)}-fc")
        if rostered is None:
            unplaced.append(name)          # reported, not guessed
        elif rostered != tier:
            wrong.append((name, "roster", rostered, tier))
    assert not wrong, f"tier disagrees with the FA allocations: {wrong}"
    assert len(unplaced) == UNPLACEABLE, sorted(unplaced)


def test_a_town_precision_coordinate_is_always_labelled_as_one():
    """
    club_master's coordinates are surveyed grounds except for a handful
    placed at a town centroid, and a reader comparing two clubs is
    entitled to know which they are looking at.
    """
    with (PROJECT_ROOT / "club_master.csv").open(encoding="utf-8-sig",
                                                 newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert "location_precision" in rows[0]
    for row in rows:
        has_coords = bool(row["latitude"].strip())
        precision = row["location_precision"].strip()
        assert (precision in {"ground", "town"}) == has_coords, row["club_id"]
