"""The most disliked clubs: four kinds scored apart, and the page."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import hatred  # noqa: E402


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_master (club_id TEXT PRIMARY KEY, canonical_name TEXT,"
                 " name_variants TEXT, lineage_parent_id TEXT, current_tier INT,"
                 " latitude REAL, longitude REAL)")
    conn.execute("CREATE TABLE standings (season_end_year INT, tier INT, division_name TEXT,"
                 " club_id TEXT, club_name TEXT, position INT, played INT, won INT, drawn INT,"
                 " lost INT, gf INT, ga INT, gd INT, points INT, status TEXT, source TEXT,"
                 " division_id TEXT)")
    for cid, name, tier, lat, lon in [("winner-fc", "Winner FC", 1, 53.0, -1.5),
                                      ("spurs-fc", "Spurs FC", 1, 53.05, -1.5),
                                      ("small-fc", "Small FC", 4, 55.0, -3.0),
                                      ("franchise-fc", "Franchise FC", 3, 52.0, -0.7)]:
        conn.execute("INSERT INTO club_master VALUES (?,?,NULL,NULL,?,?,?)", (cid, name, tier, lat, lon))

    def season(year, cid, pos, tier=1):
        conn.execute("INSERT INTO standings VALUES (?,?,'D',?,?,?,38,0,0,0,0,0,0,0,'Stayed','t','d1')",
                     (year, tier, cid, cid, pos))
    # Winner: titles in 1970 and 2024, top four otherwise. Spurs: one title
    # in 1961 and top four every second season since, never first.
    for y in range(1960, 2026):
        season(y, "winner-fc", 1 if y in (1970, 2024) else 2)
        season(y, "spurs-fc", 1 if y == 1961 else (3 if y % 2 else 8))
    season(2026, "winner-fc", 1); season(2026, "spurs-fc", 5)
    conn.execute("UPDATE standings SET status='In progress' WHERE season_end_year=2026")
    return conn


CURATED = {
    "despised": [{"club": "franchise-fc", "year": 2003, "weight": 5, "what": "Moved town."}],
    "resented": [{"club": "winner-fc", "year": 2008, "weight": 3, "what": "Bought."}],
    "wear_it": [{"club": "small-fc", "since": 1977, "line": "Nobody likes us", "what": "And so on."}],
    "eras": [{"decade": 1960, "club": "spurs-fc", "why": "Memory."},
             {"decade": 1970, "club": "winner-fc", "why": "The record."}],
    "surveys": [],
}


def test_the_four_kinds_are_scored_apart():
    rows = {r["club_id"]: r for r in hatred.score_clubs(_db(), CURATED)}
    w, s = rows["winner-fc"], rows["spurs-fc"]
    assert w["envied"] > s["envied"]                 # two titles, and one of them recent
    assert s["mocked"] > w["mocked"]                 # famous, barren
    assert w["resented"] == 3.0 and s["resented"] == 0.0   # curated ownership event only
    assert s["mocked_detail"] == {"last_title": 1961, "top_flight_seasons_since": 64, "near_misses": 32}
    assert s["mocked"] == pytest.approx(0.1 * 64 + 32)
    # the live season is not in the record
    assert w["titles"] == 2 and w["top_flight_seasons"] == 66


def test_a_club_with_no_top_flight_season_is_still_scored_if_curated():
    rows = {r["club_id"]: r for r in hatred.score_clubs(_db(), CURATED)}
    assert rows["franchise-fc"]["despised"] == 5.0
    assert rows["franchise-fc"]["success"] == 0.0 and rows["franchise-fc"]["mocked"] == 0.0
    assert "small-fc" in rows                         # wear-it clubs too
    assert "nobody-fc" not in rows


def test_an_unknown_curated_club_is_skipped_not_fatal(caplog):
    cur = dict(CURATED, despised=[{"club": "nobody-fc", "weight": 5, "what": "x"}])
    rows = hatred.score_clubs(_db(), cur)
    assert all(r["club_id"] != "nobody-fc" for r in rows)


def test_exposure_counts_neighbours_within_fifteen_miles():
    rows = {r["club_id"]: r for r in hatred.score_clubs(_db(), CURATED)}
    assert rows["winner-fc"]["exposure"]["neighbours"] == 1    # Spurs, 3.5 miles away
    assert rows["small-fc"]["exposure"]["neighbours"] == 0


def test_decade_picks_start_in_the_1960s_and_say_when_memory_differs():
    picks = {d["decade"]: d for d in hatred.decade_picks(_db(), CURATED)}
    assert min(picks) == 1960
    assert picks[1960]["model"] == "winner-fc" and picks[1960]["editorial"] == "spurs-fc"
    assert picks[1960]["agree"] is False
    assert picks[1970]["agree"] is True and picks[1970]["why"] == "The record."


def test_each_kind_is_scaled_to_its_leader_so_equal_weights_mean_equal():
    rows = [
        {"club_id": "a", "envied": 80.0, "resented": 0.0, "mocked": 0.0, "despised": 0.0},
        {"club_id": "b", "envied": 0.0, "resented": 0.0, "mocked": 0.0, "despised": 4.0},
        {"club_id": "c", "envied": 40.0, "resented": 0.0, "mocked": 0.0, "despised": 2.0},
    ]
    norm = hatred.normalised(rows)
    assert norm["a"]["envied"] == 1.0 and norm["c"]["envied"] == 0.5
    assert norm["a"]["resented"] == 0.0              # nobody resented: zero, not a division error
    index = hatred.hatred_index(norm)
    # Twenty times the raw envy, but the same index as the despised leader.
    assert index["a"] == pytest.approx(25.0) and index["b"] == pytest.approx(25.0)
    assert index["c"] == pytest.approx(25.0)
    heavy = hatred.hatred_index(norm, {"envied": 3, "resented": 0, "mocked": 0, "despised": 1})
    assert heavy["a"] == pytest.approx(75.0) and heavy["b"] == pytest.approx(25.0)
    assert hatred.hatred_index(norm, {k: 0 for k in hatred.KINDS}) == {"a": 0.0, "b": 0.0, "c": 0.0}


def test_financial_sanctions_count_only_in_the_top_flight():
    conn = _db()
    conn.execute("CREATE TABLE points_deductions (club_id TEXT, season_end_year INT, tier INT,"
                 " points INT, category TEXT, applied INT, reason TEXT, source_url TEXT, note TEXT)")
    conn.execute("INSERT INTO points_deductions VALUES ('winner-fc', 2024, 1, 6, 'financial-rules', 1, '', '', '')")
    conn.execute("INSERT INTO points_deductions VALUES ('small-fc', 2023, 3, 6, 'financial-rules', 1, '', '', '')")
    assert hatred.financial_sanctions(conn) == {"winner-fc": 1}


def test_the_page_builds_with_index_eras_and_wear_it(tmp_path, monkeypatch):
    import shutil
    import yaml

    import site_build as sb
    from site_build import SiteBuilder
    from test_digest import _make_db

    disk = tmp_path / "england.db"
    src = _make_db()
    # Coordinates switch on the site's map build, which reads stadium_name too.
    for col in ("latitude REAL", "longitude REAL", "stadium_name TEXT"):
        src.execute(f"ALTER TABLE club_master ADD COLUMN {col}")
    src.execute("INSERT INTO standings VALUES (2020, 1, 'Premier League', 'giant-fc', 'Giant FC', 1,"
                " 38, 0, 0, 0, 0, 0, 0, 0, 'Champions', 'test')")
    # Commit first: backup() from a connection holding an open write
    # transaction retries forever against its own lock.
    src.commit()
    dst = sqlite3.connect(disk); src.backup(dst); dst.close()

    content_dir = tmp_path / "content" / "insights"
    content_dir.mkdir(parents=True)
    (content_dir / "hatred.md").write_text("Why some clubs are disliked.\n", encoding="utf-8")
    (tmp_path / "content" / "hatred.yml").write_text(yaml.safe_dump({
        "despised": [], "resented": [], "surveys": [
            {"source": "Test poll", "question": "Whom?", "kind": "percent", "scores": {"giant-fc": 40}}],
        "wear_it": [{"club": "giant-fc", "since": 1990, "line": "Nobody", "what": "Cares."}],
        "eras": [{"decade": 2020, "club": "giant-fc", "why": "Won it."}],
    }), encoding="utf-8")
    shutil.copytree(Path(__file__).parent.parent / "templates", tmp_path / "templates")
    shutil.copytree(Path(__file__).parent.parent / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(hatred, "CURATED", tmp_path / "content" / "hatred.yml")
    out = tmp_path / "site"
    SiteBuilder(disk, out, charts_enabled=False).build()

    page = (out / "insights" / "hatred" / "index.html").read_text(encoding="utf-8")
    assert "Why some clubs are disliked." in page
    assert 'class="hatred-bar" data-club="giant-fc"' in page
    assert page.count('type="range"') == 4 and page.count('value="50"') == 4   # equal to start
    assert "Equal weights" in page
    assert "Test poll" in page and "40%" in page
    assert "2020s" in page and "Won it." in page and "agree" in page
    assert "Nobody" in page and "Cares." in page
    assert (out / "insights" / "hatred" / "hatred-data.js").exists()
    assert "The most disliked clubs" in (out / "insights" / "index.html").read_text(encoding="utf-8")
