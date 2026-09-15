"""The Wednesday catchment edition: five themes and a rotating profile."""

import datetime
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from test_digest import _make_db  # noqa: E402

from editions import catchment as cm  # noqa: E402
from editions import config, phrasing  # noqa: E402
from editions.catchment import CatchmentEdition  # noqa: E402
from editions.registry import WEEKDAY_EDITIONS  # noqa: E402

WEDNESDAY = datetime.date(2026, 9, 9)


def _db():
    conn = _make_db()
    conn.execute("ALTER TABLE club_master ADD COLUMN stadium_name TEXT")
    conn.execute("ALTER TABLE club_master ADD COLUMN latitude REAL")
    conn.execute("ALTER TABLE club_master ADD COLUMN longitude REAL")
    conn.execute("UPDATE club_master SET stadium_name='Giant Park', latitude=53.0, longitude=-1.5"
                 " WHERE club_id='giant-fc'")
    conn.execute("UPDATE club_master SET stadium_name='Steady Road', latitude=53.05, longitude=-1.55"
                 " WHERE club_id='steady-fc'")
    conn.execute("CREATE TABLE club_catchment (club_id TEXT, catchment_pop_current INT,"
                 " catchment_pop_restored INT, catchment_income INT, voronoi_pop INT,"
                 " contest_ratio REAL, nearest_rival_id TEXT, nearest_rival_miles REAL,"
                 " nearest_rival_tier INT, model_version TEXT)")
    conn.execute("INSERT INTO club_catchment VALUES ('giant-fc', 400000, 900000, 52000, 500000,"
                 " 0.2, 'steady-fc', 4.1, 3, 'test')")
    conn.execute("INSERT INTO club_catchment VALUES ('steady-fc', 90000, 90000, 33000, 300000,"
                 " 0.7, 'giant-fc', 4.1, 3, 'test')")
    conn.execute("CREATE TABLE msoa_demographics (msoa_code TEXT, msoa_name TEXT,"
                 " local_authority TEXT, latitude REAL, longitude REAL, population INT,"
                 " population_year INT, net_income INT, net_income_year INT,"
                 " income_ci_lower INT, income_ci_upper INT, source_url TEXT)")
    # One MSOA next to the clubs, two in a far district, one far but in a near district.
    for code, la, lat, lon, pop in [("E1", "Nearby", 53.01, -1.51, 8000),
                                    ("E2", "Far Moor", 54.2, -2.9, 6000),
                                    ("E3", "Far Moor", 54.3, -2.8, 5000),
                                    ("E4", "Nearby", 53.9, -1.5, 3000)]:
        conn.execute("INSERT INTO msoa_demographics VALUES (?,?,?,?,?,?,2022,NULL,NULL,NULL,NULL,'')",
                     (code, code, la, lat, lon, pop))
    # The current season, so the ladder rank has positions to read.
    conn.execute("INSERT INTO standings VALUES (2027,3,'League One','giant-fc','Giant FC',4,5,3,1,1,7,4,3,10,'In progress','test')")
    conn.execute("INSERT INTO standings VALUES (2027,3,'League One','steady-fc','Steady FC',9,5,1,2,2,4,6,-2,5,'In progress','test')")
    return conn


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARCHIVE_ROOT", tmp_path / "archive")
    monkeypatch.setattr(config, "PREVIEW_ROOT", tmp_path / "preview")
    return tmp_path


def test_clubs_in_scope_are_ranked_by_market_and_by_level():
    clubs = {c["club_id"]: c for c in cm.clubs_in_scope(_db(), 2027)}
    assert clubs["giant-fc"]["pop_rank"] == 1 and clubs["steady-fc"]["pop_rank"] == 2
    assert clubs["giant-fc"]["ladder_rank"] == 1 and clubs["steady-fc"]["ladder_rank"] == 2
    assert clubs["giant-fc"]["income_pct"] < 50 < clubs["steady-fc"]["income_pct"]


def test_every_theme_returns_rows():
    conn = _db()
    clubs = cm.clubs_in_scope(conn, 2027)
    names = {"giant-fc": "Giant FC", "steady-fc": "Steady FC"}
    contested = cm.theme_contested(clubs, names)
    assert contested[0]["name"] == "Steady FC" and contested[0]["contested"] == 70
    assert contested[0]["rival"] == "Giant FC" and contested[0]["rival_division"] == "League One"
    assert [r["name"] for r in cm.theme_market(clubs)] == ["Giant FC", "Steady FC"]
    assert cm.theme_overachievers(clubs) == []           # nobody in tiers 1-2
    restored = cm.theme_restored(clubs)
    assert len(restored) == 1 and restored[0]["multiple"] == 2.2 and restored[0]["ceiling"] == "Premier League"


def test_deserts_sum_people_beyond_twenty_miles_by_authority():
    conn = _db()
    rows = cm.theme_deserts(conn, cm.clubs_in_scope(conn, 2027))
    by_la = {r["authority"]: r for r in rows}
    assert by_la["Far Moor"]["people_far"] == 11000 and by_la["Far Moor"]["people"] == 11000
    assert by_la["Nearby"]["people_far"] == 3000 and by_la["Nearby"]["people"] == 11000
    assert rows[0]["authority"] == "Far Moor" and rows[0]["furthest_miles"] > 60
    assert rows[0]["nearest_club"] in ("Giant FC", "Steady FC")


def test_the_profile_rotates_through_the_archive(roots, tmp_path):
    conn = _db()
    first = CatchmentEdition(conn, WEDNESDAY, tmp_path / "c1").build()
    assert first.claims == [{"theme": first.claims[0]["theme"], "profile": first.claims[0]["profile"]}]
    profiled = first.claims[0]["profile"]
    # Archive it the way the runner would, then build the next week.
    d = config.ARCHIVE_ROOT / "catchment" / WEDNESDAY.isoformat()
    d.mkdir(parents=True)
    (d / "claims.json").write_text(json.dumps({"claims": first.claims}))
    second = CatchmentEdition(conn, WEDNESDAY + datetime.timedelta(days=7), tmp_path / "c2").build()
    assert second.claims[0]["profile"] != profiled
    assert second.claims[0]["theme"] != first.claims[0]["theme"]   # the week moved the theme on


def test_the_profile_reads_as_sentences_with_a_chart(roots, tmp_path):
    out = CatchmentEdition(_db(), WEDNESDAY, tmp_path / "c").build(theme="market", profile_id="giant-fc")
    p = out.text
    assert "Giant FC play in League One, at Giant Park." in p
    assert phrasing.division_phrase("Championship") == "the Championship"
    assert "the 1st largest catchment of the 2 clubs" in p and "by league position they are 1st" in p
    assert "The nearest club is Steady FC (League One), 4.1 miles away." in p
    assert "20% of the people nearest to them go elsewhere." in p
    assert "Restored to the Premier League, their highest recorded level, the model gives them 900,000." in p
    assert "Net household income" not in p   # two clubs sit at the 25th and 75th percentile: not extremes
    assert out.images and out.images[0][1] == "profile"
    assert out.subject == "Catchment — Big markets, low divisions — Giant FC profiled"
    assert config.club_url("giant-fc") in out.html


def test_income_is_silent_in_the_middle():
    p = {"name": "X", "division": "League One", "pop": 1, "pop_rank": 1, "ladder_rank": 1,
         "income": 40000, "income_pct": 50.0, "income_extreme": False}
    assert not any("income" in s for s in phrasing.profile_paragraphs(p, 10))


def test_thin_without_a_catchment_table(roots, tmp_path):
    conn = _make_db()
    out = CatchmentEdition(conn, WEDNESDAY, tmp_path / "c").build()
    assert out.thin and out.profile is None if hasattr(out, "profile") else out.thin
    assert out.claims == [{"theme": out.claims[0]["theme"], "profile": None}]


def test_clubs_outside_england_are_measured_but_never_ranked(roots, tmp_path):
    conn = _db()
    conn.execute("INSERT INTO club_master VALUES ('swansea-city-fc','Swansea City',NULL,NULL,2,"
                 "'Swansea.com Stadium',51.64,-3.94)")
    conn.execute("INSERT INTO club_catchment VALUES ('swansea-city-fc', 5000, 5000, NULL, 5000,"
                 " 0.5, 'giant-fc', 80.0, 3, 'test')")
    clubs = cm.clubs_in_scope(conn, 2027)
    swansea = next(c for c in clubs if c["club_id"] == "swansea-city-fc")
    assert swansea["outside_england"] and "pop_rank" not in swansea
    assert cm.choose_profile([c for c in clubs if not c["outside_england"]])["club_id"] != "swansea-city-fc"
    out = CatchmentEdition(conn, WEDNESDAY, tmp_path / "c").build(theme="overachievers")
    assert "Swansea" not in out.html          # tier 2, would top the smallest-market table
    deserts = cm.theme_deserts(conn, clubs)
    assert deserts                            # still measured from every ground


def test_wednesday_is_scheduled():
    assert WEEKDAY_EDITIONS[3] == "catchment"
