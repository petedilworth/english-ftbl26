import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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
