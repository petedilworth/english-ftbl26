"""Which club to buy: the levers, the index, and the page."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import value  # noqa: E402


def test_percentile_shares_ties_keeps_gaps_and_can_run_backwards():
    p = value.percentile({"a": 1.0, "b": 2.0, "c": 2.0, "d": 3.0, "e": None})
    assert p == {"a": 0.0, "b": 0.5, "c": 0.5, "d": 1.0, "e": None}
    assert value.percentile({"a": 1.0, "b": 3.0}, higher_is_better=False) == {"a": 1.0, "b": 0.0}
    assert value.percentile({"a": 7.0}) == {"a": 0.5}


def test_the_index_is_a_weighted_mean_with_a_gap_counted_at_the_middle():
    levers = {"climb": 1.0, "cheap": 0.0, "wages": None}
    assert value.value_index(levers) == pytest.approx(100 * (1.0 + 0.0 + 0.5) / 3)
    assert value.value_index(levers, {"climb": 3, "cheap": 1, "wages": 0}) == pytest.approx(75.0)
    assert value.value_index(levers, {"climb": 0, "cheap": 0, "wages": 0}) == 0.0


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_trajectory (club_id TEXT, canonical_name TEXT, current_tier INT,"
                 " natural_level_gap INT, highest_tier INT, seasons_in_tier1 INT, yo_yo_score REAL)")
    conn.execute("CREATE TABLE standings (season_end_year INT, tier INT, club_id TEXT,"
                 " position INT, tier_position INT, status TEXT)")
    conn.execute("CREATE TABLE points_deductions (club_id TEXT, season_end_year INT)")
    conn.execute("CREATE TABLE club_finances (club_id TEXT, season_end_year INT, turnover REAL,"
                 " staff_costs REAL, profit_before_tax REAL)")
    conn.execute("CREATE TABLE club_catchment (club_id TEXT, catchment_pop_restored INT,"
                 " catchment_income INT, contest_ratio REAL)")
    clubs = [
        # id, tier now, gap, highest, top-flight seasons, yo-yo
        ("fallen-fc", 3, 2, 1, 20, 0.3),
        ("steady-fc", 3, 0, 3, 0, 0.0),
        ("big-fc", 1, 0, 1, 60, 0.1),
        ("gone-fc", 2, 1, 1, 10, 0.2),      # dissolved: last tier 2, not in this season
    ]
    for cid, tier, gap, high, top, yoyo in clubs:
        conn.execute("INSERT INTO club_trajectory VALUES (?,?,?,?,?,?,?)",
                     (cid, cid.replace("-", " ").title(), tier, gap, high, top, yoyo))
    # 2023 finished: fallen-fc 5th in tier 3. 2026 finished: 1st. 2027 in progress.
    rows = [(2023, 1, "big-fc", 1), (2023, 3, "fallen-fc", 5), (2023, 3, "steady-fc", 2),
            (2023, 2, "gone-fc", 3),
            (2026, 1, "big-fc", 1), (2026, 3, "fallen-fc", 1), (2026, 3, "steady-fc", 2),
            (2027, 1, "big-fc", 1), (2027, 3, "fallen-fc", 1), (2027, 3, "steady-fc", 2)]
    for year, tier, cid, pos in rows:
        conn.execute("INSERT INTO standings VALUES (?,?,?,?,?,?)",
                     (year, tier, cid, pos, pos, "In progress" if year == 2027 else "Stayed"))
    conn.execute("INSERT INTO points_deductions VALUES ('fallen-fc', 2024)")
    conn.executemany("INSERT INTO club_finances VALUES (?,?,?,?,?)", [
        ("fallen-fc", 2025, 20e6, 18e6, -5e6), ("steady-fc", 2025, 10e6, 5e6, 1e6)])
    conn.executemany("INSERT INTO club_catchment VALUES (?,?,?,?)", [
        ("fallen-fc", 900_000, 35_000, 0.2), ("steady-fc", 50_000, 45_000, 0.9),
        ("big-fc", 3_000_000, 40_000, 0.5)])
    return conn


FACTS = {
    "fallen-fc": {"capacity": 30000, "stadium_ownership": "club", "fan_owned": [{"year": 1990}]},
    "steady-fc": {"capacity": 4000, "ownership_model": "fan_trust", "pitch_type": "artificial_3g"},
}


def test_the_levers_on_a_small_pyramid():
    rows = {r["club_id"]: r for r in value.score_clubs(_db(), FACTS)}
    assert set(rows) == {"fallen-fc", "steady-fc", "big-fc"}         # gone-fc is not in this season
    f, s, b = rows["fallen-fc"]["levers"], rows["steady-fc"]["levers"], rows["big-fc"]["levers"]
    assert f["climb"] == 1.0 and s["climb"] == b["climb"] == 0.25    # two below its level; ties share
    # 7th in the pyramid in 2023 (behind big, gone and 4 in tier 3), 2nd in 2026.
    assert rows["fallen-fc"]["raw"]["momentum"] == "up 5 places in 3 seasons"
    assert f["momentum"] == 1.0
    assert f["clean"] == 0.0 and s["clean"] == 1.0                    # docked in 2024: recent
    assert s["wages"] == 1.0 and f["wages"] == 0.0                    # 50% beats 90%
    assert b["wages"] is None and b["owns_ground"] is None            # no accounts, no facts
    assert f["owns_ground"] == 1.0
    assert b["cheap"] == 0.0 and s["cheap"] == 1.0                    # top of the pyramid costs most
    assert b["steady"] == 0.5 and s["steady"] == 1.0                  # lower yo-yo scores higher
    # Fan ownership is today's model, not the history list.
    assert rows["steady-fc"]["fan_owned"] and not rows["fallen-fc"]["fan_owned"]
    assert rows["steady-fc"]["flags"] == ["fan-owned", "artificial pitch"]


def test_the_page_builds_with_equal_sliders_and_the_accounts_box(tmp_path, monkeypatch):
    import shutil

    import site_build as sb
    from site_build import SiteBuilder
    from test_digest import _make_db

    disk = tmp_path / "england.db"
    src = _make_db()
    src.commit()
    dst = sqlite3.connect(disk); src.backup(dst); dst.close()

    content_dir = tmp_path / "content" / "insights"
    content_dir.mkdir(parents=True)
    (content_dir / "value.md").write_text("Buy low, climb.\n", encoding="utf-8")
    shutil.copytree(Path(__file__).parent.parent / "templates", tmp_path / "templates")
    shutil.copytree(Path(__file__).parent.parent / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "site"
    SiteBuilder(disk, out, charts_enabled=False).build()

    page = (out / "insights" / "value" / "index.html").read_text(encoding="utf-8")
    assert "Buy low, climb." in page
    n = len(value.LEVERS)
    assert page.count('type="range"') == n and page.count('value="50"') == n   # equal to start
    assert 'class="value-money" checked' in page and "Equal weights" in page
    assert 'class="index-bar" data-club=' in page
    assert (out / "insights" / "value" / "value-data.js").exists()
    assert "Which club to buy" in (out / "insights" / "index.html").read_text(encoding="utf-8")
