"""
The Wednesday catchment edition: tied to the week's fixtures, one claim
per section, a map as evidence.

A four-club world: two neighbours three miles apart (the shared ground),
a top-flight club on a small market, and a fifth-tier club on a large one.
"""

import datetime
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from test_digest import _make_db  # noqa: E402

import catchment  # noqa: E402
from editions import catchment as cm  # noqa: E402
from editions import config, maps, phrasing  # noqa: E402
from editions.catchment import CatchmentEdition  # noqa: E402
from editions.registry import WEEKDAY_EDITIONS  # noqa: E402

WEDNESDAY = datetime.date(2026, 9, 16)
NAMES = {"giant-fc": "Giant FC", "steady-fc": "Steady FC", "alpha-fc": "Alpha FC", "beta-fc": "Beta FC"}
GROUNDS = {"giant-fc": (53.00, -1.50), "steady-fc": (53.03, -1.55),
           "alpha-fc": (51.50, -0.10), "beta-fc": (52.40, -3.00)}


def _db(extra_clubs=()):
    conn = _make_db()
    for col in ("stadium_name TEXT", "latitude REAL", "longitude REAL"):
        conn.execute(f"ALTER TABLE club_master ADD COLUMN {col}")
    conn.execute("INSERT INTO club_master (club_id, canonical_name, current_tier) VALUES ('alpha-fc','Alpha FC',1)")
    conn.execute("INSERT INTO club_master (club_id, canonical_name, current_tier) VALUES ('beta-fc','Beta FC',5)")
    for cid, (lat, lon) in GROUNDS.items():
        conn.execute("UPDATE club_master SET latitude=?, longitude=? WHERE club_id=?", (lat, lon, cid))
    for cid, name, tier, lat, lon in extra_clubs:
        conn.execute("INSERT INTO club_master (club_id, canonical_name, current_tier, latitude, longitude)"
                     " VALUES (?,?,?,?,?)", (cid, name, tier, lat, lon))
    # The current season: alpha top of the pyramid, beta fifth tier.
    for cid, tier, pos in [("alpha-fc", 1, 1), ("giant-fc", 3, 1), ("steady-fc", 3, 2), ("beta-fc", 5, 1)]:
        conn.execute("INSERT INTO standings VALUES (2027,?,?,?,?,?,5,3,1,1,7,4,3,10,'In progress','t')",
                     (tier, "x", cid, NAMES[cid], pos))
    conn.execute("CREATE TABLE msoa_demographics (msoa_code TEXT, msoa_name TEXT, local_authority TEXT,"
                 " latitude REAL, longitude REAL, population INT, population_year INT, net_income INT,"
                 " net_income_year INT, income_ci_lower INT, income_ci_upper INT, source_url TEXT)")
    # Around each ground: alpha tiny, beta huge, the neighbours in between.
    pops = {"alpha-fc": 1_000, "beta-fc": 60_000, "giant-fc": 9_000, "steady-fc": 7_000}
    n = 0
    for cid, (lat, lon) in GROUNDS.items():
        for dlat, dlon in [(0.02, 0), (-0.02, 0), (0, 0.03), (0, -0.03)]:
            n += 1
            conn.execute("INSERT INTO msoa_demographics VALUES (?,?,?,?,?,?,2022,NULL,NULL,NULL,NULL,'')",
                         (f"E{n:03d}", f"E{n:03d}", f"{cid}-la", lat + dlat, lon + dlon, pops[cid]))
    return conn


def _fixtures():
    return [
        {"div": "E2", "tier": 3, "division_name": "League One", "date": datetime.date(2026, 9, 19),
         "time": "15:00", "home_name": "Giant FC", "away_name": "Steady FC",
         "home_id": "giant-fc", "away_id": "steady-fc"},
        {"div": "E0", "tier": 1, "division_name": "Premier League", "date": datetime.date(2026, 9, 20),
         "time": "15:00", "home_name": "Alpha FC", "away_name": "Beta FC",
         "home_id": "alpha-fc", "away_id": "beta-fc"},
    ]


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARCHIVE_ROOT", tmp_path / "archive")
    monkeypatch.setattr(config, "PREVIEW_ROOT", tmp_path / "preview")
    return tmp_path


def _build(tmp_path, conn=None, fixtures=None):
    return CatchmentEdition(conn or _db(), WEDNESDAY, tmp_path / "charts").build(
        fixture_list=_fixtures() if fixtures is None else fixtures)


# ── the model ──────────────────────────────────────────────────────────────

def test_a_doorstep_is_split_between_clubs_and_the_shares_add_up():
    m = catchment.current_shares(_db())
    turf = m.turf_people("giant-fc")
    drawn = sum(m.takes(c, "giant-fc") for c in m.club_ids)
    assert turf == 36_000 and drawn == pytest.approx(turf)
    kept = m.takes("giant-fc", "giant-fc")
    assert 0 < kept < turf
    assert m.takers("giant-fc")[0][0] == "steady-fc"      # the neighbour takes most of the rest


# ── the edition ────────────────────────────────────────────────────────────

def test_the_lead_is_the_fixture_whose_clubs_share_the_most_people(roots, tmp_path):
    out = _build(tmp_path)
    lead = out.claims[0]["lead"]
    assert lead == ["giant-fc", "steady-fc"]
    assert out.subject == "Catchment — Giant FC v Steady FC, and whose people they are"


def test_each_doorstep_sentence_uses_that_doorsteps_own_people(roots, tmp_path):
    """The opponent's share is of THIS club's doorstep - a swapped
    denominator once reported West Ham drawing 13% of Millwall's people
    when the model said 7%."""
    conn = _db()
    m = catchment.current_shares(conn)
    out = _build(tmp_path, conn)
    turf = m.turf_people("giant-fc")
    kept = round(100 * m.takes("giant-fc", "giant-fc") / turf)
    steady = round(100 * m.takes("steady-fc", "giant-fc") / turf)
    assert f"Giant FC draw {kept}% of them; Steady FC draw {steady}%." in out.text


def test_bigger_and_smaller_than_their_division(roots, tmp_path):
    out = _build(tmp_path)
    text = out.text
    assert "BIGGER THAN THEIR DIVISION: BETA FC" in text
    assert "SMALLER THAN THEIR DIVISION: ALPHA FC" in text
    assert "the 1st largest market of the 4 clubs" in text          # beta
    assert "They sit 1st in the pyramid: 1st in the Premier League." in text   # alpha
    assert sorted(out.claims[0]["featured"]) == sorted(NAMES)


def test_every_section_has_a_map(roots, tmp_path):
    out = _build(tmp_path)
    cids = [cid for _, cid in out.images]
    assert cids == ["map-lead", "map-bigger", "map-smaller"]
    assert all(p.exists() and p.stat().st_size > 5_000 for p, _ in out.images)
    for cid in cids:
        assert f"cid:{cid}" in out.html


def test_clubs_featured_in_the_last_month_are_not_featured_again(roots, tmp_path):
    d = config.ARCHIVE_ROOT / "catchment" / "2026-09-09"
    d.mkdir(parents=True)
    (d / "claims.json").write_text(json.dumps({"claims": [{"featured": ["beta-fc"], "lead": None}]}))
    out = _build(tmp_path)
    assert "beta-fc" not in out.claims[0]["featured"]
    assert "BETA FC" not in out.text


def test_welsh_clubs_are_never_featured(roots, tmp_path):
    conn = _db(extra_clubs=[("swansea-city-fc", "Swansea City", 2, 51.64, -3.94)])
    conn.execute("INSERT INTO standings VALUES (2027,2,'x','swansea-city-fc','Swansea City',1,5,3,1,1,7,4,3,10,'In progress','t')")
    fx = _fixtures() + [{"div": "E1", "tier": 2, "division_name": "Championship",
                         "date": datetime.date(2026, 9, 19), "time": "15:00",
                         "home_name": "Swansea City", "away_name": "Alpha FC",
                         "home_id": "swansea-city-fc", "away_id": "alpha-fc"}]
    out = _build(tmp_path, conn, fx)
    assert "swansea-city-fc" not in out.claims[0]["featured"]
    assert "SWANSEA" not in out.text


def test_an_empty_fixture_list_is_refused(roots, tmp_path):
    out = _build(tmp_path, fixtures=[])
    assert out.refuse and out.thin and out.images == []


def test_the_map_skips_a_club_the_model_does_not_know(tmp_path):
    m = catchment.current_shares(_db())
    assert maps.catchment_map(m, ["nobody-fc"], NAMES, tmp_path / "x.png") is None
    path = maps.catchment_map(m, ["giant-fc", "steady-fc"], NAMES, tmp_path / "y.png",
                              region_of=["giant-fc", "steady-fc"])
    assert path and path.exists()


def test_people_are_rounded_and_percentages_whole():
    assert phrasing._people(306_812) == "307,000"
    assert phrasing._people(1_594_898) == "1.6 million"
    assert phrasing._pct(0.4949) == "49%"


def test_wednesday_is_scheduled():
    assert WEEKDAY_EDITIONS[3] == "catchment"
