"""Income around the ground: the weighted spread, the tier model, and the page."""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import income  # noqa: E402


def test_weighted_stats_follow_the_people_not_the_places():
    values = np.array([20000.0, 40000.0, 60000.0])
    heavy_poor = income._weighted(values, np.array([8.0, 1.0, 1.0]))
    assert heavy_poor["mean"] == pytest.approx(26000.0)
    assert heavy_poor["p10"] == 20000.0 and heavy_poor["p90"] == 60000.0
    flat = income._weighted(np.array([30000.0, 30000.0]), np.array([1.0, 1.0]))
    assert flat["sd"] == 0.0
    assert income._weighted(values, np.zeros(3)) is None


def test_the_tier_model_reads_size_not_income():
    people = [1_000_000, 300_000, 100_000, 30_000, 10_000, 3_000]
    tiers = [1, 2, 3, 4, 5, 6]
    a, b, r2, pred = income.tier_model(tiers, people)
    assert b < 0 and r2 > 0.99                  # more people, lower tier number
    assert pred[0] == pytest.approx(1, abs=0.2)
    assert income.tier_model([3, 3, 3], [1, 2, 3])[2] == 0.0   # nothing to explain


def _england():
    """Two towns: a rich small one with a tier-7 club, a poor big one with a tier-1 club."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_master (club_id TEXT PRIMARY KEY, canonical_name TEXT, current_tier INT,"
                 " latitude REAL, longitude REAL)")
    conn.execute("CREATE TABLE standings (club_id TEXT, season_end_year INT, tier INT, status TEXT,"
                 " division_name TEXT, position INT)")
    conn.execute("CREATE TABLE msoa_demographics (msoa_code TEXT, msoa_name TEXT, local_authority TEXT,"
                 " latitude REAL, longitude REAL, population INT, population_year INT, net_income INT,"
                 " net_income_year INT, income_ci_lower INT, income_ci_upper INT, source_url TEXT)")
    conn.executemany("INSERT INTO club_master VALUES (?,?,?,?,?)", [
        ("big-fc", "Big FC", 1, 53.5, -2.5), ("posh-fc", "Posh FC", 7, 51.4, -0.3)])
    conn.executemany("INSERT INTO standings VALUES (?,?,?,?,?,?)", [
        ("big-fc", 2027, 1, "In progress", "Premier League", 3), ("posh-fc", 2027, 7, "In progress", "Isthmian", 5)])
    rows = []
    for k in range(8):   # the big poor town: eight neighbourhoods around Big FC, one of them well-off
        rows.append((f"B{k}", f"Bigtown {k:03d}", "Bigtown", 53.5 + 0.02 * k, -2.5, 20000, 2023,
                     30000 + (25000 if k == 7 else 0), 2023, 27000, 33000, "ons"))
    for k in range(2):   # the small rich town
        rows.append((f"P{k}", f"Poshtown {k:03d}", "Poshtown", 51.4 + 0.02 * k, -0.3, 6000, 2023, 60000, 2023, 54000, 66000, "ons"))
    conn.executemany("INSERT INTO msoa_demographics VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return conn


def test_assemble_finds_the_rich_small_club_and_the_poor_big_one():
    d = income.assemble(_england())
    by = {c["club_id"]: c for c in d["clubs"]}
    big, posh = by["big-fc"], by["posh-fc"]
    assert posh["mean"] > big["mean"] and big["people"] > posh["people"]
    assert big["sd"] > posh["sd"]                              # the one rich suburb makes Bigtown unequal
    assert big["richest"]["name"] == "Bigtown 007" and big["poorest"]["income"] == 30000
    assert posh["sd"] < 1000 and posh["gap"] == 0                # a sliver of Bigtown reaches it; the tenths do not
    assert d["by_tier"][1]["n"] == 1 and d["by_tier"][7]["n"] == 1
    assert d["england"]["mean"] == pytest.approx((8 * 20000 * 30000 + 20000 * 25000 + 12000 * 60000) / 172000, abs=1)
    m = d["map"]
    assert len(m["points"]) == 10 and m["names"][0] == "000" and m["authorities"][m["las"][0]] == "Bigtown"
    assert len(m["ramp"]) == len(income.RAMP) and len(m["edges"]) == len(income.RAMP) - 1
    assert [p[4] for p in m["points"][:8]] == [0] * 8          # Big FC draws most of every Bigtown neighbourhood


def test_assemble_is_empty_without_demographics():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_master (club_id TEXT, current_tier INT, latitude REAL, longitude REAL)")
    conn.execute("CREATE TABLE standings (club_id TEXT, season_end_year INT, tier INT)")
    conn.execute("CREATE TABLE msoa_demographics (msoa_code TEXT, local_authority TEXT, latitude REAL,"
                 " longitude REAL, population INT, net_income INT)")
    assert income.assemble(conn) == {}


def test_the_page_builds_with_the_map_data_and_the_strip(tmp_path, monkeypatch):
    import shutil

    import site_build as sb
    from site_build import SiteBuilder

    src = _england()
    # The site builder needs the rest of the schema; borrow the standard test database and add ours.
    from test_digest import _make_db
    full = _make_db()
    for col in ("latitude REAL", "longitude REAL", "stadium_name TEXT"):
        full.execute(f"ALTER TABLE club_master ADD COLUMN {col}")
    full.execute("UPDATE club_master SET latitude = 53.5, longitude = -2.5 WHERE club_id = 'giant-fc'")
    full.execute("UPDATE club_master SET latitude = 51.4, longitude = -0.3 WHERE club_id = 'steady-fc'")
    full.execute("CREATE TABLE msoa_demographics (msoa_code TEXT, msoa_name TEXT, local_authority TEXT,"
                 " latitude REAL, longitude REAL, population INT, population_year INT, net_income INT,"
                 " net_income_year INT, income_ci_lower INT, income_ci_upper INT, source_url TEXT)")
    full.executemany("INSERT INTO msoa_demographics VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     src.execute("SELECT * FROM msoa_demographics").fetchall())
    full.commit()
    disk = tmp_path / "england.db"
    dst = sqlite3.connect(disk); full.backup(dst); dst.close()

    content_dir = tmp_path / "content" / "insights"
    content_dir.mkdir(parents=True)
    (content_dir / "income.md").write_text("Follow the money.\n", encoding="utf-8")
    shutil.copytree(Path(__file__).parent.parent / "templates", tmp_path / "templates")
    shutil.copytree(Path(__file__).parent.parent / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "site"
    SiteBuilder(disk, out, charts_enabled=False).build()

    page = (out / "insights" / "income" / "index.html").read_text(encoding="utf-8")
    assert "Follow the money." in page and 'id="income-map"' in page
    assert "Does money around the ground buy tiers?" in page and "Between wealth and poverty" in page
    assert "Giant FC" in page and "Steady FC" in page
    data = (out / "insights" / "income" / "income-data.js").read_text(encoding="utf-8")
    assert data.startswith("window.INCOME_DATA = {") and '"authorities"' in data
    assert "Income around the ground" in (out / "insights" / "index.html").read_text(encoding="utf-8")
