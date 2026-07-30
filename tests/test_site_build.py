import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import trajectory
from site_build import SiteBuilder, season_label, season_slug
from test_digest import _make_db


def _db_on_disk(tmp_path):
    """Copy the in-memory fixture DB to a file (SiteBuilder opens a path)."""
    mem = _make_db()
    path = tmp_path / "test.db"
    disk = sqlite3.connect(path)
    mem.backup(disk)
    disk.close()
    return path


def test_season_slug_and_label():
    assert season_slug(1994) == "1993-94"
    assert season_slug(2000) == "1999-00"
    assert season_slug(2001) == "2000-01"
    assert season_label(2025) == "2024/25"


def test_full_build_renders_all_pages(tmp_path):
    db = _db_on_disk(tmp_path)
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()

    assert (out / "index.html").exists()
    assert (out / "seasons" / "index.html").exists()
    assert (out / "season" / "2024-25" / "index.html").exists()
    assert (out / "division" / "index.html").exists()
    assert (out / "division" / "league-one" / "index.html").exists()
    assert (out / "teams" / "index.html").exists()
    assert (out / "team" / "giant-fc" / "index.html").exists()
    assert (out / "insights" / "index.html").exists()
    assert (out / "static" / "style.css").exists()
    assert (out / ".nojekyll").exists()

    home = (out / "index.html").read_text()
    assert "2024/25" in home
    assert "Giant FC" in home

    team = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "Fallen giant" in team          # tagline logic engaged
    assert "still to come" in team          # narrative placeholder
    assert "League One" in team


def test_narrative_markdown_rendered(tmp_path, monkeypatch):
    db = _db_on_disk(tmp_path)
    out = tmp_path / "site"

    # Point the builder at a temp content dir with one narrative
    import site_build as sb
    content = tmp_path / "content"
    content.mkdir()
    (content / "giant-fc.md").write_text("Their **glory years** were brief.")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    # templates/static still need the real project root; copy them over
    import shutil
    real_root = Path(__file__).parent.parent
    shutil.copytree(real_root / "templates", tmp_path / "templates")
    shutil.copytree(real_root / "static", tmp_path / "static")

    SiteBuilder(db, out, charts_enabled=False).build()
    team = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "<strong>glory years</strong>" in team
    assert "still to come" not in team


def test_team_chart_generated(tmp_path):
    db = _db_on_disk(tmp_path)
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=True).build()
    assert (out / "team" / "giant-fc" / "chart.png").exists()
    team = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "chart.png" in team


def _promotion_db(tmp_path):
    """A club promoted from tier 2 to tier 1 - a genuine 'promoted' event."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE club_master (club_id TEXT PRIMARY KEY, canonical_name TEXT,"
        " name_variants TEXT, lineage_parent_id TEXT, current_tier INT)"
    )
    conn.execute(
        "CREATE TABLE standings (season_end_year INT, tier INT, division_name TEXT,"
        " club_id TEXT, club_name TEXT, position INT, played INT, won INT, drawn INT,"
        " lost INT, gf INT, ga INT, gd INT, points INT, status TEXT, source TEXT)"
    )
    conn.execute("INSERT INTO club_master VALUES ('riser-fc','Riser FC',NULL,NULL,1)")
    for year, tier, pos, status in [(2023, 2, 1, "Champions"), (2024, 1, 15, "Stayed")]:
        conn.execute(
            "INSERT INTO standings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (year, tier, "Div", "riser-fc", "Riser FC", pos,
             46, 20, 10, 16, 60, 50, 10, 70, status, "test"),
        )
    trajectory.rebuild_trajectory(conn)
    path = tmp_path / "promo.db"
    disk = sqlite3.connect(path)
    conn.backup(disk)
    disk.close()
    return path


def test_chart_data_includes_events_and_tier_floors(tmp_path):
    db = _promotion_db(tmp_path)
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()

    payload = json.loads(
        (out / "chart" / "chart-data.js")
        .read_text()
        .replace("window.CHART_DATA = ", "")
        .rstrip(";")
    )
    assert payload["tierFloors"]
    riser = next(c for c in payload["clubs"] if c["id"] == "riser-fc")
    assert [pt[2] for pt in riser["series"]] == ["promoted", None]


def test_matrix_is_one_table_most_recent_first(tmp_path):
    db = _db_on_disk(tmp_path)
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()

    matrix = (out / "matrix" / "index.html").read_text()

    # Single shared table, not one per division, so every row scrolls together
    assert matrix.count("<table class=\"matrix\">") == 1

    # Most recent season appears before older ones (left-to-right order)
    assert matrix.index("2024/25") < matrix.index("2023/24") < matrix.index("2022/23")

    # Every division with any data becomes its own row
    assert "Premier League" in matrix
    assert "Championship" in matrix
    assert "League One" in matrix

    # Clubs still carry data-club for the highlight script, regardless of table shape
    assert 'data-club="giant-fc"' in matrix


def test_insights_and_map_pages(tmp_path):
    db = _db_on_disk(tmp_path)
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()

    for slug in ("yo-yo", "fallen-giants", "records", "timeline"):
        assert (out / "insights" / slug / "index.html").exists(), slug

    fallen = (out / "insights" / "fallen-giants" / "index.html").read_text()
    assert "Giant FC" in fallen

    timeline = (out / "insights" / "timeline" / "index.html").read_text()
    assert "Bury" in timeline

    # Fixture DB has no stadium coordinates -> map is skipped gracefully
    assert not (out / "map" / "index.html").exists()

    # Digest archive renders its empty state
    assert (out / "digest" / "index.html").exists()


def test_map_page_built_when_coordinates_exist(tmp_path):
    mem = _make_db()
    mem.execute("ALTER TABLE club_master ADD COLUMN color_primary TEXT")
    mem.execute("ALTER TABLE club_master ADD COLUMN color_secondary TEXT")
    mem.execute("ALTER TABLE club_master ADD COLUMN stadium_name TEXT")
    mem.execute("ALTER TABLE club_master ADD COLUMN latitude REAL")
    mem.execute("ALTER TABLE club_master ADD COLUMN longitude REAL")
    mem.execute(
        "UPDATE club_master SET stadium_name='Test Park', latitude=52.5,"
        " longitude=-1.9, color_primary='#123456'"
    )
    mem.commit()  # backup() spins forever on a pending write transaction
    path = tmp_path / "map.db"
    disk = sqlite3.connect(path)
    mem.backup(disk)
    disk.close()

    out = tmp_path / "site"
    SiteBuilder(path, out, charts_enabled=False).build()
    assert (out / "map" / "index.html").exists()
    data = (out / "map" / "map-data.js").read_text()
    assert "Test Park" in data and "giant-fc" in data
