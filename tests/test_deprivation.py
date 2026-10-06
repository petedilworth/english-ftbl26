"""Deprivation around the ground: percentiles, weighting, and the page."""

import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import deprivation as dp  # noqa: E402
from test_income import _england  # noqa: E402  (two towns: a big poor one, a small rich one)


def test_percentiles_follow_people_not_places():
    # Three places; the most deprived holds most of the people, so it sits high.
    p = dp.percentiles([10.0, 20.0, 30.0], [1.0, 1.0, 8.0])
    assert p[0] < p[1] < p[2]
    assert p[2] == pytest.approx(60.0)          # the middle of the top 80% of people
    assert dp.percentiles([5.0, 5.0], [1.0, 1.0]).tolist() == pytest.approx([25.0, 75.0])


def test_the_index_is_a_weighted_mean_and_zero_weights_read_as_average():
    rows = np.array([[80.0, 20.0], [40.0, 60.0]])
    assert dp.index(rows, [1, 0]).tolist() == [80.0, 40.0]
    assert dp.index(rows, [1, 1]).tolist() == [50.0, 50.0]
    assert dp.index(rows, [0, 0]).tolist() == [50.0, 50.0]


def _write_csv(tmp_path, conn):
    """A deprivation file for the two towns: Bigtown deprived on everything but housing."""
    rows = conn.execute("SELECT msoa_code, msoa_name FROM msoa_demographics").fetchall()
    lines = ["msoa_code,msoa_name,lsoas,population,imd," + ",".join(dp.KEYS) + ",imd_rank,imd_decile"]
    for i, (code, name) in enumerate(rows):
        big = code.startswith("B")
        vals = [40.0 if big else 10.0 for _ in dp.KEYS]
        vals[dp.KEYS.index("housing")] = 5.0 if big else 30.0
        lines.append(f"{code},{name},4,20000,{40.0 if big else 10.0}," + ",".join(str(v) for v in vals)
                     + f",{i + 1},{1 if big else 10}")
    path = tmp_path / "msoa_deprivation.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_assemble_gives_each_club_a_shape(tmp_path):
    conn = _england()
    d = dp.assemble(conn, _write_csv(tmp_path, conn))
    by = {c["club_id"]: c for c in d["clubs"]}
    big, posh = by["big-fc"], by["posh-fc"]
    h = dp.KEYS.index("housing")
    assert big["d"][0] > 50 > posh["d"][0]            # deprived on income
    assert big["d"][h] < 50 < posh["d"][h]            # but not on housing
    assert big["bottom10"] > posh["bottom10"]
    assert len(d["map"]["points"]) == 10 and len(d["map"]["points"][0]) == 2 + len(dp.KEYS)
    assert [x["key"] for x in d["domains"]] == dp.KEYS


def test_assemble_is_empty_without_the_file_or_its_overall_score(tmp_path):
    assert dp.assemble(_england(), tmp_path / "missing.csv") == {}
    bad = tmp_path / "bad.csv"
    bad.write_text("msoa_code,msoa_name," + ",".join(dp.KEYS) + "\n", encoding="utf-8")
    assert dp.assemble(_england(), bad) == {}


def test_the_page_builds_with_sliders_and_data(tmp_path, monkeypatch):
    import site_build as sb
    from site_build import SiteBuilder
    from test_digest import _make_db

    src = _england()
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

    (tmp_path / "data").mkdir()
    shutil.copy(_write_csv(tmp_path, src), tmp_path / "data" / "msoa_deprivation.csv")
    content_dir = tmp_path / "content" / "insights"
    content_dir.mkdir(parents=True)
    (content_dir / "deprivation.md").write_text("Hard times, seven ways.\n", encoding="utf-8")
    shutil.copytree(Path(__file__).parent.parent / "templates", tmp_path / "templates")
    shutil.copytree(Path(__file__).parent.parent / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "site"
    SiteBuilder(disk, out, charts_enabled=False).build()

    page = (out / "insights" / "deprivation" / "index.html").read_text(encoding="utf-8")
    assert "Hard times, seven ways." in page and 'id="dep-map"' in page
    assert page.count('class="chip dep-solo"') == len(dp.KEYS)
    assert page.count('type="range"') == len(dp.KEYS) and 'step="0.1"' in page   # 9.3 must be reachable
    for heading in ("Build your own deprivation", "Deprivation, tier and size", "Where deprivation and income disagree",
                    "In England's most deprived tenth", "Children and pensioners", "Every club"):
        assert heading in page
    data = (out / "insights" / "deprivation" / "deprivation-data.js").read_text(encoding="utf-8")
    assert data.startswith("window.DEPRIVATION_DATA = {") and '"domains"' in data
    assert "Deprivation around the ground" in (out / "insights" / "index.html").read_text(encoding="utf-8")
