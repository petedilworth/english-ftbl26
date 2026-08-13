import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import trajectory
from site_build import SiteBuilder, _facts_rows, season_label, season_slug
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


def _build_with_content(tmp_path, monkeypatch, files: dict):
    """
    Build the site with a temp content/ dir. files maps club_id -> markdown.
    Templates and static are copied from the real project root.
    """
    import shutil

    import site_build as sb

    db = _db_on_disk(tmp_path)
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    for club_id, text in files.items():
        (content_dir / f"{club_id}.md").write_text(text, encoding="utf-8")

    real_root = Path(__file__).parent.parent
    shutil.copytree(real_root / "templates", tmp_path / "templates")
    shutil.copytree(real_root / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)

    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()
    return out


RICH_STORY = """---
founded: 1905
origin_type: works
ownership_model: fan_trust
owner: The Supporters' Trust
owner_since: 2003
stadium: Test Park
capacity: 8696
stadium_ownership: council
administration:
  - year: 2010
    points_deducted: 9
exile:
  - venue: Somewhere Else
    seasons: 1997-1999
    distance_miles: 70
---
## Origins
Formed by factory workers.

## Ownership & Finance
The trust took control after near-collapse.

## Kit history
An unrecognised section that should still appear.
"""


def test_team_page_renders_sections_facts_and_chips(tmp_path, monkeypatch):
    out = _build_with_content(tmp_path, monkeypatch, {"giant-fc": RICH_STORY})
    page = (out / "team" / "giant-fc" / "index.html").read_text()

    # Named sections, in canonical order (Origins before Ownership)
    assert page.index("Origins") < page.index("Ownership &amp; Finance")
    assert "Formed by factory workers." in page
    assert "The trust took control" in page

    # Unrecognised heading kept rather than dropped
    assert "Kit history" in page

    # Facts panel
    assert "Club facts" in page
    assert "Fan / supporters&#39; trust" in page or "Fan / supporters' trust" in page
    assert "8,696" in page
    assert "Council-owned" in page
    assert "Somewhere Else" in page

    # Theme chips link to theme pages
    assert 'href="../../themes/fan-owned/index.html"' in page
    assert "placeholder" not in page.lower()


def test_theme_pages_generated_from_facts(tmp_path, monkeypatch):
    out = _build_with_content(tmp_path, monkeypatch, {"giant-fc": RICH_STORY})

    index = (out / "themes" / "index.html").read_text()
    assert "Fan-owned clubs" in index

    for slug in ("fan-owned", "administration", "exiled"):
        page = (out / "themes" / slug / "index.html").read_text()
        assert "Giant FC" in page, slug

    # steady-fc has no story file, so must not appear on any theme page
    assert "Steady FC" not in (out / "themes" / "fan-owned" / "index.html").read_text()


def test_retired_theme_pages_are_not_built(tmp_path, monkeypatch):
    # council-ground, multi-club and stadium-moves were retired. RICH_STORY
    # carries stadium_ownership: council and administration (which used to
    # be enough to qualify for council-ground); confirm no page or tile
    # exists for any of the three even so.
    out = _build_with_content(tmp_path, monkeypatch, {"giant-fc": RICH_STORY})
    for slug in ("council-ground", "multi-club", "stadium-moves"):
        assert not (out / "themes" / slug / "index.html").exists(), slug
    index = (out / "themes" / "index.html").read_text()
    assert "Council-owned" not in index
    assert "multi-club group" not in index.lower()
    assert "moved ground" not in index.lower()


def test_club_without_story_keeps_placeholder(tmp_path, monkeypatch):
    out = _build_with_content(tmp_path, monkeypatch, {"giant-fc": RICH_STORY})
    page = (out / "team" / "steady-fc" / "index.html").read_text()
    assert "still to come" in page
    assert "Club facts" not in page      # no empty furniture
    assert "theme-chip" not in page


def test_themes_index_renders_empty_state_with_no_stories(tmp_path, monkeypatch):
    out = _build_with_content(tmp_path, monkeypatch, {})
    index = (out / "themes" / "index.html").read_text()
    assert "Themes appear here" in index


# ── Theme pages: intro, chart, events, narrative ───────────────────────

THEMED_STORY = """---
founded: 1883
ownership_model: fan_trust
owner: The Supporters' Trust
owner_since: 2003
stadium: Test Park
administration:
  - year: 2010
    points_deducted: 9
    note: Followed a rent dispute
exile:
  - venue: Somewhere Else
    seasons: 1985-1991
---
## Origins
Formed by factory workers.
"""


def _build_with_theme_intros(tmp_path, monkeypatch, files, intros):
    """As _build_with_content, but also seeds content/themes/<slug>.md."""
    import shutil

    import site_build as sb

    db = _db_on_disk(tmp_path)
    content_dir = tmp_path / "content"
    (content_dir / "themes").mkdir(parents=True)
    for club_id, text in files.items():
        (content_dir / f"{club_id}.md").write_text(text, encoding="utf-8")
    for slug, text in intros.items():
        (content_dir / "themes" / f"{slug}.md").write_text(text, encoding="utf-8")

    real_root = Path(__file__).parent.parent
    shutil.copytree(real_root / "templates", tmp_path / "templates")
    shutil.copytree(real_root / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)

    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()
    return out


def test_theme_page_has_intro_chart_and_derived_narrative(tmp_path, monkeypatch):
    out = _build_with_theme_intros(
        tmp_path, monkeypatch,
        {"giant-fc": THEMED_STORY},
        {"administration": "Why insolvency reshapes a club."},
    )
    page = (out / "themes" / "administration" / "index.html").read_text()

    assert "Why insolvency reshapes a club." in page       # intro prose
    assert "trajectory-chart" in page                      # the chart
    assert "chart-detail" in page                          # click-for-detail panel
    # Narrative derived from facts, no hand-authoring needed
    assert "2010" in page and "9 points" in page and "rent dispute" in page


def test_theme_chart_preselects_every_club_in_the_theme(tmp_path, monkeypatch):
    out = _build_with_theme_intros(
        tmp_path, monkeypatch, {"giant-fc": THEMED_STORY}, {})
    payload = json.loads(
        (out / "themes" / "administration" / "chart-data.js")
        .read_text().replace("window.CHART_DATA = ", "").rstrip(";")
    )
    assert payload["preselect"] == ["giant-fc"]
    club = payload["clubs"][0]
    assert club["events"][0]["season_end_year"] == 2011   # 2010 calendar -> 2010/11
    assert club["events"][0]["text"]


def test_events_before_the_records_are_flagged_not_dropped(tmp_path, monkeypatch):
    # The exile starts in 1985; the fixture DB's standings start later, so the
    # dot has nowhere to sit. It must still be reported in the narrative.
    out = _build_with_theme_intros(
        tmp_path, monkeypatch, {"giant-fc": THEMED_STORY}, {})
    page = (out / "themes" / "exiled" / "index.html").read_text()
    assert "Somewhere Else" in page
    assert "before the records begin" in page


def test_theme_without_intro_file_still_builds(tmp_path, monkeypatch):
    out = _build_with_theme_intros(
        tmp_path, monkeypatch, {"giant-fc": THEMED_STORY}, {})
    page = (out / "themes" / "administration" / "index.html").read_text()
    assert "theme-intro" not in page       # no empty furniture
    assert "Giant FC" in page


def test_global_chart_still_starts_empty(tmp_path):
    # The theme charts preselect; the global one must not, or it draws
    # every club in the database at once.
    db = _db_on_disk(tmp_path)
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()
    payload = json.loads(
        (out / "chart" / "chart-data.js")
        .read_text().replace("window.CHART_DATA = ", "").rstrip(";")
    )
    assert payload["preselect"] == []


# ── Natural level ──────────────────────────────────────────────────────

def _level_db(tmp_path):
    """A club with enough history to be classified, plus a thin one."""
    conn = _make_db()
    conn.execute("INSERT INTO club_master VALUES ('longrun-fc','Longrun FC',NULL,NULL,2)")
    for year in range(2005, 2026):
        tier = 2 if year < 2020 else 3
        conn.execute(
            "INSERT INTO standings (season_end_year, tier, division_name, club_id,"
            " club_name, position, played, won, drawn, lost, gf, ga, gd, points,"
            " status, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (year, tier, "Div", "longrun-fc", "Longrun FC", 5,
             46, 20, 10, 16, 60, 50, 10, 70, "Stayed", "test"),
        )
    trajectory.rebuild_trajectory(conn)
    conn.commit()
    path = tmp_path / "level.db"
    disk = sqlite3.connect(path)
    conn.backup(disk)
    disk.close()
    return path


def test_natural_level_panel_rendered(tmp_path):
    out = tmp_path / "site"
    SiteBuilder(_level_db(tmp_path), out, charts_enabled=False).build()
    page = (out / "team" / "longrun-fc" / "index.html").read_text()

    assert "Where they've played" in page
    assert "Natural level" in page          # the stat card
    assert "nl-seg" in page                 # the distribution bar
    # The era caveat must travel with the claim
    assert "pre-Premier League era" in page


def test_thin_club_has_no_natural_level_panel(tmp_path):
    # giant-fc in the shared fixture has only a couple of seasons
    out = tmp_path / "site"
    SiteBuilder(_db_on_disk(tmp_path), out, charts_enabled=False).build()
    page = (out / "team" / "giant-fc" / "index.html").read_text()
    # No panel, and no row of dashes pretending to be one
    assert "Where they've played" not in page
    assert "nl-seg" not in page


def test_natural_level_insight_page_built(tmp_path):
    out = tmp_path / "site"
    SiteBuilder(_level_db(tmp_path), out, charts_enabled=False).build()
    page = (out / "insights" / "natural-level" / "index.html").read_text()
    assert "Playing above their level" in page
    assert "Playing below their level" in page
    assert "Above and below their level" in (out / "insights" / "index.html").read_text()


# ── Nickname ─────────────────────────────────────────────────────────

def test_facts_rows_includes_nickname_when_present():
    rows = _facts_rows({"nickname": "the Posh", "founded": 1934})
    labels = [r["label"] for r in rows]
    assert "Nickname" in labels
    assert rows[labels.index("Nickname")]["value"] == "the Posh"


def test_facts_rows_omits_nickname_when_absent():
    rows = _facts_rows({"founded": 1934})
    assert "Nickname" not in [r["label"] for r in rows]


NICKNAME_STORY = """---
founded: 1934
nickname: the Posh
capacity: 8696
---
## Origins
Traditionally attributed to a 1921 remark about wanting posh players.
"""


def test_team_page_header_shows_nickname(tmp_path, monkeypatch):
    out = _build_with_content(tmp_path, monkeypatch, {"giant-fc": NICKNAME_STORY})
    page = (out / "team" / "giant-fc" / "index.html").read_text()
    assert '<span class="nickname">"the Posh"</span>' in page


def test_team_page_header_has_no_nickname_span_when_absent(tmp_path, monkeypatch):
    out = _build_with_content(tmp_path, monkeypatch, {"giant-fc": RICH_STORY})
    page = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "nickname" not in page


# ── Capacity vs. position insight ───────────────────────────────────────

def test_capacity_insight_plots_a_club_with_capacity_and_current_standings(tmp_path, monkeypatch):
    # RICH_STORY (giant-fc) already carries capacity: 8696; the shared
    # fixture DB has giant-fc in tier 3, position 8, in the latest season.
    out = _build_with_content(tmp_path, monkeypatch, {"giant-fc": RICH_STORY})
    page = (out / "insights" / "capacity" / "index.html").read_text()
    assert page.count("<circle") == 1
    assert "8,696" in page  # tooltip capacity, comma-formatted
    assert "Stadium size vs" in (out / "insights" / "index.html").read_text()


def _build_capacity_db(tmp_path, extra_rows=(), extra_clubs=()):
    """
    The shared fixture DB (test_digest._make_db) plus extra standings rows
    and extra club_master rows, for tests that need seasons or clubs beyond
    what the shared fixture provides. extra_rows are full 16-column
    standings tuples; extra_clubs are (club_id, name, tier) triples.
    """
    db = _db_on_disk(tmp_path)
    conn = sqlite3.connect(db)
    for club_id, name, tier in extra_clubs:
        conn.execute(
            "INSERT INTO club_master VALUES (?,?,NULL,NULL,?)",
            (club_id, name, tier),
        )
    for row in extra_rows:
        conn.execute(
            "INSERT INTO standings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row
        )
    trajectory.rebuild_trajectory(conn)
    conn.commit()
    conn.close()
    return db


def _build_site_with_content(tmp_path, monkeypatch, db, files: dict):
    """Like _build_with_content, but against a caller-supplied db path."""
    import shutil
    import site_build as sb

    content_dir = tmp_path / "content"
    content_dir.mkdir()
    for club_id, text in files.items():
        (content_dir / f"{club_id}.md").write_text(text, encoding="utf-8")
    real_root = Path(__file__).parent.parent
    shutil.copytree(real_root / "templates", tmp_path / "templates")
    shutil.copytree(real_root / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()
    return out


def test_capacity_insight_shows_a_club_only_on_its_own_seasons_page(tmp_path, monkeypatch):
    # A club whose story has capacity but who only appeared in an older
    # season must not be plotted on the CURRENT season's page (it has no
    # row there) - but with the season selector, it should still show up
    # on its own season's page, since capacity itself isn't season-scoped.
    old_season_story = """---
founded: 1990
capacity: 5000
---
## Origins
Test club with a stale standings record.
"""
    # Shared fixture DB spans 2022-2025 (four seasons); 2020 lands well
    # inside a 6-season "current + 5 prior" window once added.
    db = _build_capacity_db(
        tmp_path,
        extra_clubs=[("stale-fc", "Stale FC", 5)],
        extra_rows=[(
            2020, 5, "National League", "stale-fc", "Stale FC",
            10, 46, 15, 10, 21, 50, 60, -10, 55, "Stayed", "test",
        )],
    )
    out = _build_site_with_content(
        tmp_path, monkeypatch, db, {"giant-fc": RICH_STORY, "stale-fc": old_season_story}
    )

    current_page = (out / "insights" / "capacity" / "index.html").read_text()
    assert current_page.count("<circle") == 1  # giant-fc only, not stale-fc
    assert "Stale FC" not in current_page

    own_season_page = (out / "insights" / "capacity" / season_slug(2020) / "index.html").read_text()
    assert "Stale FC" in own_season_page
    assert "5,000" in own_season_page  # same capacity as it would show anywhere


def test_capacity_insight_omits_a_season_older_than_the_past_five(tmp_path, monkeypatch):
    # Only the current season plus its five predecessors get pages/tabs;
    # a club whose only row is further back than that must not appear
    # anywhere, and no page should exist for its season.
    old_story = """---
capacity: 3000
---
## Origins
Older than the six-season window.
"""
    # Shared DB seasons: 2022-2025 (4 distinct years). Adding 2019-2021
    # brings the total to 7 distinct seasons; the window (current + 5
    # prior) is then the six most recent - 2020-2025 - dropping 2019.
    # filler-fc pads the season count without ever being a capacity
    # candidate (it gets no content file), so 2020 exists as a season in
    # its own right rather than only via edge-fc.
    db = _build_capacity_db(
        tmp_path,
        extra_clubs=[
            ("edge-fc", "Edge FC", 5),
            ("ancient-fc", "Ancient FC", 5),
            ("filler-fc", "Filler FC", 5),
        ],
        extra_rows=[
            (2021, 5, "National League", "edge-fc", "Edge FC",
             5, 46, 15, 10, 21, 50, 60, -10, 55, "Stayed", "test"),
            (2019, 5, "National League", "ancient-fc", "Ancient FC",
             5, 46, 15, 10, 21, 50, 60, -10, 55, "Stayed", "test"),
            (2020, 5, "National League", "filler-fc", "Filler FC",
             5, 46, 15, 10, 21, 50, 60, -10, 55, "Stayed", "test"),
        ],
    )
    out = _build_site_with_content(
        tmp_path, monkeypatch, db, {"edge-fc": old_story, "ancient-fc": old_story}
    )

    # 2021 is inside the six-season window - it gets a page, and edge-fc
    # is on it.
    edge_page = (out / "insights" / "capacity" / season_slug(2021) / "index.html").read_text()
    assert "Edge FC" in edge_page

    # 2019 falls outside the window entirely - no page, and no tab on any
    # other season's page links to it.
    assert not (out / "insights" / "capacity" / season_slug(2019) / "index.html").exists()
    assert season_slug(2019) not in edge_page
    assert "Ancient FC" not in edge_page


def test_capacity_insight_tabs_omit_a_season_with_no_plottable_points(tmp_path, monkeypatch):
    # A season none of the storied clubs have a Tiers 1-5 row in (here,
    # the shared fixture's 2023 season has no *other* standings for our
    # single custom club) must not get its own page or tab link, even
    # though it exists in the standings table via an unrelated club.
    gap_story = """---
capacity: 6000
---
## Origins
Present in some seasons, absent in others.
"""
    db = _build_capacity_db(
        tmp_path,
        extra_clubs=[("gap-fc", "Gap FC", 5)],
        extra_rows=[
            (2024, 5, "National League", "gap-fc", "Gap FC",
             3, 46, 15, 10, 21, 50, 60, -10, 55, "Stayed", "test"),
            # No gap-fc row for 2023, even though 2023 exists in the
            # standings table (via the shared fixture's other clubs).
        ],
    )
    out = _build_site_with_content(tmp_path, monkeypatch, db, {"gap-fc": gap_story})

    gap_2024_page = (out / "insights" / "capacity" / season_slug(2024) / "index.html").read_text()
    assert "Gap FC" in gap_2024_page
    assert season_slug(2023) not in gap_2024_page  # no tab for the gap season
    assert not (out / "insights" / "capacity" / season_slug(2023) / "index.html").exists()


def test_capacity_insight_absent_when_no_capacity_data(tmp_path, monkeypatch):
    plain_story = "## Origins\nNo facts at all, just prose.\n"
    out = _build_with_content(tmp_path, monkeypatch, {"giant-fc": plain_story})
    assert not (out / "insights" / "capacity" / "index.html").exists()
    assert "Stadium size vs" not in (out / "insights" / "index.html").read_text()


def test_capacity_insight_y_axis_never_goes_negative(tmp_path, monkeypatch):
    # A small club's padded minimum must clamp at 0, not go negative -
    # capacity can't be a negative number of people.
    tiny_story = "---\ncapacity: 500\n---\n## Origins\nA small ground.\n"
    out = _build_with_content(tmp_path, monkeypatch, {"giant-fc": tiny_story})
    page = (out / "insights" / "capacity" / "index.html").read_text()
    axis_labels = re.findall(r'x="60"[^>]*>([\d,]+)</text>', page)
    assert len(axis_labels) == 2          # cap_min and cap_max labels
    assert all(not label.startswith("-") for label in axis_labels)


# ── Boom and bust insight ────────────────────────────────────────────────

def _build_with_insight_content(tmp_path, monkeypatch, files, insight_prose=None):
    """As _build_with_content, but also seeds content/insights/boom-and-bust.md."""
    import shutil

    import site_build as sb

    db = _db_on_disk(tmp_path)
    content_dir = tmp_path / "content"
    (content_dir / "insights").mkdir(parents=True)
    for club_id, text in files.items():
        (content_dir / f"{club_id}.md").write_text(text, encoding="utf-8")
    if insight_prose is not None:
        (content_dir / "insights" / "boom-and-bust.md").write_text(
            insight_prose, encoding="utf-8"
        )

    real_root = Path(__file__).parent.parent
    shutil.copytree(real_root / "templates", tmp_path / "templates")
    shutil.copytree(real_root / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)

    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()
    return out


BOOM_BUST_STORY = """---
administration:
  - year: 2013
    points_deducted: 10
    note: Followed a rent dispute
points_deductions:
  - season_end_year: 2014
    points: 10
    reason: Imposed after a rejected CVA
---
## Origins
A club with real financial trouble on record.
"""

BOOM_BUST_PROSE = """---
case_study_promoted: giant-fc
case_study_relegated: steady-fc
---
The financial cliff between divisions, explained.
"""


def test_boom_and_bust_page_builds_with_prose_stats_and_events(tmp_path, monkeypatch):
    out = _build_with_insight_content(
        tmp_path, monkeypatch, {"giant-fc": BOOM_BUST_STORY}, BOOM_BUST_PROSE
    )
    page = (out / "insights" / "boom-and-bust" / "index.html").read_text()

    assert "financial cliff between divisions" in page   # markdown prose rendered
    assert "Clubs affected" in page                       # stats block
    assert "Administration" in page and "Points deduction" in page
    assert "Docked 10 points in 2013/14" in page
    assert "Boom and bust" in (out / "insights" / "index.html").read_text()


def test_boom_and_bust_points_lost_counts_points_deductions_only(tmp_path, monkeypatch):
    # administration.points_deducted and points_deductions.points both carry
    # 10 here, describing the SAME real penalty (as several actual club
    # files do) - the stat must not double it to 20.
    out = _build_with_insight_content(
        tmp_path, monkeypatch, {"giant-fc": BOOM_BUST_STORY}, BOOM_BUST_PROSE
    )
    page = (out / "insights" / "boom-and-bust" / "index.html").read_text()
    assert '<div class="stat-value">10</div><div class="stat-label">Points deductions on record</div>' in page


def test_boom_and_bust_case_study_uses_live_trajectory_data(tmp_path, monkeypatch):
    out = _build_with_insight_content(
        tmp_path, monkeypatch, {"giant-fc": BOOM_BUST_STORY}, BOOM_BUST_PROSE
    )
    page = (out / "insights" / "boom-and-bust" / "index.html").read_text()
    assert "This past summer" in page
    assert "Promoted" in page and "Relegated" in page
    assert "Giant FC" in page and "Steady FC" in page


def test_boom_and_bust_absent_when_no_events_anywhere(tmp_path, monkeypatch):
    plain_story = "## Origins\nNo financial facts at all.\n"
    out = _build_with_insight_content(
        tmp_path, monkeypatch, {"giant-fc": plain_story}, BOOM_BUST_PROSE
    )
    assert not (out / "insights" / "boom-and-bust" / "index.html").exists()
    assert "Boom and bust" not in (out / "insights" / "index.html").read_text()


def test_boom_and_bust_works_without_a_case_study_file(tmp_path, monkeypatch):
    # No content/insights/boom-and-bust.md at all - the page should still
    # build from the table data alone, just without prose or a case study.
    out = _build_with_insight_content(
        tmp_path, monkeypatch, {"giant-fc": BOOM_BUST_STORY}, insight_prose=None
    )
    page = (out / "insights" / "boom-and-bust" / "index.html").read_text()
    assert "Administration" in page
    assert "This past summer" not in page


def test_insight_table_existing_callers_unaffected_by_new_optional_blocks(tmp_path):
    # yo-yo, records etc. never pass intro_html/stats/case studies - confirm
    # those pages still render cleanly with the new template blocks in place.
    db = _db_on_disk(tmp_path)
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()
    yoyo = (out / "insights" / "yo-yo" / "index.html").read_text()
    assert "This past summer" not in yoyo
    assert "stat-cards" not in yoyo


# ── Drops/rises as club facts (The drop / The rise featured cards) ───────
#
# giant-fc's fixture history (test_digest._make_db) has a real back-to-back
# relegation: Tier 1 -> Tier 2 in 2022, Tier 2 -> Tier 3 in 2023, then
# "Stayed" at Tier 3 through 2025 - so a drops: entry with season: 2023
# matches the pattern's final season, and the outcome is "stuck" (still at
# the floor it fell to).

DROP_STORY = """---
drops:
  - season: 2023
    note: A real fall, with a real story.
---
## Origins
A club that fell twice.
"""

DROP_STORY_TWO_NOTES = """---
drops:
  - season: 2023
    note: First note on the same fall.
  - season: 2023
    note: Second note on the same fall.
---
## Origins
A club that fell twice.
"""

DROP_STORY_WRONG_SEASON = """---
drops:
  - season: 1999
    note: This season never happened for this club.
---
## Origins
A club that fell twice.
"""


def test_drops_field_produces_a_featured_card(tmp_path, monkeypatch):
    out = _build_with_insight_content(tmp_path, monkeypatch, {"giant-fc": DROP_STORY})
    page = (out / "insights" / "the-drop" / "index.html").read_text()
    assert "A real fall, with a real story." in page
    assert "case-study-card" in page


def test_drops_field_also_shows_on_the_clubs_own_facts_panel(tmp_path, monkeypatch):
    out = _build_with_insight_content(tmp_path, monkeypatch, {"giant-fc": DROP_STORY})
    team = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "Featured on The drop" in team
    assert "A real fall, with a real story." in team


def test_drops_entry_with_no_matching_season_is_skipped_not_fatal(tmp_path, monkeypatch):
    out = _build_with_insight_content(
        tmp_path, monkeypatch, {"giant-fc": DROP_STORY_WRONG_SEASON}
    )
    # The page still builds (giant-fc's real pattern still populates the
    # table), it just has no featured card for this non-match.
    page = (out / "insights" / "the-drop" / "index.html").read_text()
    assert "This season never happened" not in page
    assert "case-study-card" not in page
    assert "Giant FC" in page  # the underlying pattern still renders below


def test_multiple_drops_entries_all_produce_cards(tmp_path, monkeypatch):
    out = _build_with_insight_content(
        tmp_path, monkeypatch, {"giant-fc": DROP_STORY_TWO_NOTES}
    )
    page = (out / "insights" / "the-drop" / "index.html").read_text()
    assert "First note on the same fall." in page
    assert "Second note on the same fall." in page
    assert page.count("case-study-card") == 2


def test_rises_field_is_independent_of_drops(tmp_path, monkeypatch):
    # steady-fc never moves tier in the fixture, so it has no rise pattern -
    # a rises: entry on it must not appear anywhere, and must not error.
    story = """---
rises:
  - season: 2023
    note: Should never appear - steady-fc has no promotion pattern.
---
## Origins
Nothing happens here.
"""
    out = _build_with_insight_content(tmp_path, monkeypatch, {"steady-fc": story})
    assert not (out / "insights" / "the-rise" / "index.html").exists()


# ── Rivalries & derbies ────────────────────────────────────────────────

RIVALRY_STORY = """---
rivalries:
  - opponent: steady-fc
    name: The Test Derby
    note: A grudge born from a real, researched cause.
---
## Origins
A club with a documented rival.
"""

RIVALRY_STORY_UNNAMED = """---
rivalries:
  - opponent: steady-fc
    note: Unnamed but documented all the same.
---
## Origins
A club with a documented rival.
"""

RIVALRY_STORY_UNKNOWN_OPPONENT = """---
rivalries:
  - opponent: not-a-real-club-fc
    note: Should be skipped, not fatal.
---
## Origins
A club with a bogus rival.
"""


def test_rivalries_page_builds_with_named_derby(tmp_path, monkeypatch):
    out = _build_with_insight_content(tmp_path, monkeypatch, {"giant-fc": RIVALRY_STORY})
    page = (out / "insights" / "rivalries" / "index.html").read_text()
    assert "The Test Derby" in page
    assert "A grudge born from a real, researched cause." in page
    assert "Giant FC" in page and "Steady FC" in page


def test_rivalries_page_falls_back_to_club_names_when_unnamed(tmp_path, monkeypatch):
    out = _build_with_insight_content(
        tmp_path, monkeypatch, {"giant-fc": RIVALRY_STORY_UNNAMED}
    )
    page = (out / "insights" / "rivalries" / "index.html").read_text()
    assert "Giant FC" in page and "Steady FC" in page
    assert "Unnamed but documented all the same." in page


def test_rivalry_shows_on_the_clubs_own_facts_panel_with_opponent_name(tmp_path, monkeypatch):
    out = _build_with_insight_content(tmp_path, monkeypatch, {"giant-fc": RIVALRY_STORY})
    team = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "Rivalry" in team
    assert "Steady FC" in team
    assert "A grudge born from a real, researched cause." in team


def test_rivalry_with_unknown_opponent_is_skipped_not_fatal(tmp_path, monkeypatch):
    out = _build_with_insight_content(
        tmp_path, monkeypatch, {"giant-fc": RIVALRY_STORY_UNKNOWN_OPPONENT}
    )
    assert not (out / "insights" / "rivalries" / "index.html").exists()


def test_rivalry_written_on_both_sides_is_deduped_not_doubled(tmp_path, monkeypatch):
    other_side = """---
rivalries:
  - opponent: giant-fc
    name: The Test Derby
    note: A shorter note from the other side.
---
## Origins
The other half of the same rivalry.
"""
    out = _build_with_insight_content(
        tmp_path, monkeypatch,
        {"giant-fc": RIVALRY_STORY, "steady-fc": other_side},
    )
    page = (out / "insights" / "rivalries" / "index.html").read_text()
    # Only the longer, more detailed note survives - shown once, not twice.
    assert page.count("The Test Derby") == 1
    assert "A grudge born from a real, researched cause." in page
    assert "A shorter note from the other side." not in page


def test_rivalries_page_absent_when_no_rivalries_anywhere(tmp_path, monkeypatch):
    out = _build_with_insight_content(tmp_path, monkeypatch, {"giant-fc": DROP_STORY})
    assert not (out / "insights" / "rivalries" / "index.html").exists()
    assert "Rivalries" not in (out / "insights" / "index.html").read_text()


def test_rivalry_opponent_with_no_team_page_shows_name_without_a_dead_link(
    tmp_path, monkeypatch
):
    # A club can be in club_master (and have a content file) without a
    # club_trajectory row - e.g. it hasn't played Tiers 1-5 since before
    # the 1993/94 data start (Bradford Park Avenue in the real data). Its
    # name should still resolve, but build_teams() never renders a page
    # for it, so the rivalries table must not link to one that 404s.
    import shutil

    import site_build as sb

    db = _db_on_disk(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO club_master VALUES ('ghost-fc','Ghost FC',NULL,NULL,7)"
    )
    conn.commit()
    conn.close()

    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "giant-fc.md").write_text(
        """---
rivalries:
  - opponent: ghost-fc
    name: The Haunted Derby
    note: A rivalry with a club that has no page of its own.
---
## Origins
A club with a ghostly rival.
""",
        encoding="utf-8",
    )
    real_root = Path(__file__).parent.parent
    shutil.copytree(real_root / "templates", tmp_path / "templates")
    shutil.copytree(real_root / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)

    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()

    assert not (out / "team" / "ghost-fc").exists()
    page = (out / "insights" / "rivalries" / "index.html").read_text()
    assert "Ghost FC" in page
    assert '<a href="../../team/ghost-fc/index.html">Ghost FC</a>' not in page


# ── Club finances: loader and the financial scatter metrics ──────────────
# Figures come from statutory accounts. The two things that silently corrupt
# this data are recording a figure against the wrong legal entity, and mixing
# incompatible definitions of "wages" (the staff-costs note excludes transfer
# amortisation; some sources include it, a ~20-40% difference). Both are
# columns, and the loader refuses rows that contradict themselves.

import finances


def _finances_csv(tmp_path, rows: list[dict]) -> Path:
    """Write a club_finances.csv with the canonical column order."""
    import csv as csv_mod

    path = tmp_path / "club_finances.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv_mod.writer(fh)
        writer.writerow(finances.COLUMNS)
        for row in rows:
            writer.writerow([row.get(c, "") for c in finances.COLUMNS])
    return path


def _full_row(club_id, season, **over):
    row = {
        "club_id": club_id, "season_end_year": season,
        "company_number": "01234567", "entity_name": f"{club_id} Ltd",
        "consolidation_level": "club", "period_start": f"{season - 1}-07-01",
        "period_end": f"{season}-06-30", "period_months": 12,
        "disclosure": "full", "turnover": 10_000_000,
        "staff_costs": 6_000_000, "staff_costs_definition": "excl_amortisation",
        "source_url": "https://example.invalid", "filing_date": f"{season}-12-01",
    }
    row.update(over)
    return row


def _seeded(tmp_path, rows):
    db = _db_on_disk(tmp_path)
    conn = sqlite3.connect(db)
    loaded = finances.seed_club_finances(conn, _finances_csv(tmp_path, rows))
    conn.commit()
    return db, conn, loaded


def test_finances_csv_round_trips_into_the_table(tmp_path):
    _db, conn, loaded = _seeded(tmp_path, [_full_row("giant-fc", 2024)])
    assert loaded == 1
    row = conn.execute(
        "SELECT turnover, staff_costs, staff_costs_definition, entity_name"
        " FROM club_finances WHERE club_id='giant-fc' AND season_end_year=2024"
    ).fetchone()
    assert row == (10_000_000, 6_000_000, "excl_amortisation", "giant-fc Ltd")


def test_finances_row_absent_from_the_csv_is_removed(tmp_path):
    # The CSV is the single source of truth, as for club_master.
    db, conn, _ = _seeded(tmp_path, [_full_row("giant-fc", 2024),
                                     _full_row("giant-fc", 2023)])
    assert conn.execute("SELECT COUNT(*) FROM club_finances").fetchone()[0] == 2
    finances.seed_club_finances(conn, _finances_csv(tmp_path, [_full_row("giant-fc", 2024)]))
    remaining = conn.execute(
        "SELECT season_end_year FROM club_finances"
    ).fetchall()
    assert remaining == [(2024,)]


def test_finances_rejects_a_non_disclosing_row_that_carries_figures(tmp_path):
    # A club that filed small-company accounts cannot also have published a
    # turnover; keeping both would attribute real money to a club that never
    # disclosed any.
    _db, conn, loaded = _seeded(tmp_path, [
        _full_row("giant-fc", 2024, disclosure="small_company"),
    ])
    assert loaded == 0
    assert conn.execute("SELECT COUNT(*) FROM club_finances").fetchone()[0] == 0


def test_finances_rejects_staff_costs_without_a_definition(tmp_path):
    _db, _conn, loaded = _seeded(tmp_path, [
        _full_row("giant-fc", 2024, staff_costs_definition=""),
    ])
    assert loaded == 0


def test_finances_rejects_a_club_not_in_club_master(tmp_path):
    _db, _conn, loaded = _seeded(tmp_path, [_full_row("nonexistent-fc", 2024)])
    assert loaded == 0


def test_finances_keeps_a_non_disclosure_row_as_a_state(tmp_path):
    # Non-disclosure is a finding, not a gap: the row is kept, with no figures.
    _db, conn, loaded = _seeded(tmp_path, [
        _full_row("giant-fc", 2024, disclosure="small_company",
                  turnover="", staff_costs="", staff_costs_definition=""),
    ])
    assert loaded == 1
    assert conn.execute(
        "SELECT disclosure, turnover FROM club_finances"
    ).fetchone() == ("small_company", None)


def _build_with_finances(tmp_path, monkeypatch, rows, files=None):
    db = _db_on_disk(tmp_path)
    conn = sqlite3.connect(db)
    finances.seed_club_finances(conn, _finances_csv(tmp_path, rows))
    conn.commit()
    conn.close()
    # _finances_csv wrote into tmp_path, which _build_site_with_content also
    # uses as PROJECT_ROOT - harmless, the site build never reads the CSV.
    return _build_site_with_content(tmp_path, monkeypatch, db, files or {"giant-fc": RICH_STORY})


def test_revenue_metric_renders_its_own_page(tmp_path, monkeypatch):
    out = _build_with_finances(tmp_path, monkeypatch, [_full_row("giant-fc", 2025)])
    page = (out / "insights" / "finances" / "revenue" / "index.html").read_text()
    assert page.count("<circle") == 1
    assert "£10.0m revenue" in page
    assert "Revenue vs. league position" in (out / "insights" / "index.html").read_text()


def test_log_scale_keeps_a_club_three_orders_smaller_inside_the_frame(tmp_path, monkeypatch):
    # Revenue spans ~£1.5m in the National League to £700m+ at the top. On a
    # linear axis everything below the Premier League collapses onto the
    # baseline, which is why these metrics are logarithmic.
    db = _build_capacity_db(
        tmp_path,
        extra_clubs=[("tiny-fc", "Tiny FC", 5), ("mid-fc", "Mid FC", 3)],
        extra_rows=[
            (2025, 5, "National League", "tiny-fc", "Tiny FC",
             12, 46, 15, 10, 21, 50, 60, -10, 55, "Stayed", "test"),
            (2025, 3, "League One", "mid-fc", "Mid FC",
             6, 46, 18, 10, 18, 55, 55, 0, 64, "Stayed", "test"),
        ],
    )
    conn = sqlite3.connect(db)
    finances.seed_club_finances(conn, _finances_csv(tmp_path, [
        _full_row("giant-fc", 2025, turnover=600_000_000, staff_costs=300_000_000),
        _full_row("mid-fc", 2025, turnover=10_000_000, staff_costs=6_000_000),
        _full_row("tiny-fc", 2025, turnover=1_500_000, staff_costs=1_100_000),
    ]))
    conn.commit()
    conn.close()
    out = _build_site_with_content(tmp_path, monkeypatch, db, {"giant-fc": RICH_STORY})

    page = (out / "insights" / "finances" / "revenue" / "index.html").read_text()
    by_name = {
        m.group(2): float(m.group(1))
        for m in re.finditer(
            r'circle cx="[\d.]+" cy="([\d.-]+)"[^>]*>[^<]*<title>([A-Za-z ]+?) —', page
        )
    }
    assert len(by_name) == 3
    # Frame runs from plot_top=16 to plot_bottom=344.
    assert all(16 <= cy <= 344 for cy in by_name.values())
    # The discriminating case: on a linear axis a £10m club against a £600m
    # maximum sits at ~1.7% of the range, i.e. crushed onto the baseline.
    # Logarithmic spacing puts it near the middle instead.
    assert by_name["Mid FC"] < 300, "mid-sized club collapsed onto the baseline"
    assert by_name["Giant FC"] < by_name["Mid FC"] < by_name["Tiny FC"]


def test_profit_metric_plots_a_loss_below_the_zero_line(tmp_path, monkeypatch):
    out = _build_with_finances(tmp_path, monkeypatch, [
        _full_row("giant-fc", 2025, profit_before_tax=-20_000_000),
    ])
    page = (out / "insights" / "finances" / "profit" / "index.html").read_text()
    zero_y = float(re.search(r'stroke="#c8ced6"', page) and
                   re.search(r'y1="([\d.]+)" x2="\d+" y2="[\d.]+"\s*\n?\s*stroke="#c8ced6"', page).group(1))
    point_y = float(re.search(r'circle cx="[\d.]+" cy="([\d.-]+)"', page).group(1))
    assert point_y > zero_y  # SVG y grows downward, so a loss sits below
    assert "−£20.0m" in page


def test_wage_ratio_is_derived_and_shows_the_benchmark(tmp_path, monkeypatch):
    # Two clubs either side of UEFA's 70% line, so the benchmark is on-scale.
    db = _build_capacity_db(
        tmp_path,
        extra_clubs=[("thrifty-fc", "Thrifty FC", 3)],
        extra_rows=[(2025, 3, "League One", "thrifty-fc", "Thrifty FC",
                     12, 46, 15, 10, 21, 50, 60, -10, 55, "Stayed", "test")],
    )
    conn = sqlite3.connect(db)
    finances.seed_club_finances(conn, _finances_csv(tmp_path, [
        _full_row("giant-fc", 2025, turnover=10_000_000, staff_costs=7_300_000),
        _full_row("thrifty-fc", 2025, turnover=10_000_000, staff_costs=5_000_000),
    ]))
    conn.commit()
    conn.close()
    out = _build_site_with_content(tmp_path, monkeypatch, db, {"giant-fc": RICH_STORY})

    page = (out / "insights" / "finances" / "wage-ratio" / "index.html").read_text()
    assert "73%" in page and "50%" in page   # derived, not stored
    assert "UEFA benchmark" in page


def test_wage_ratio_absent_when_an_input_is_missing(tmp_path, monkeypatch):
    # With no staff_costs there is nothing to divide, so no page at all.
    out = _build_with_finances(
        tmp_path, monkeypatch,
        [_full_row("giant-fc", 2025, staff_costs="", staff_costs_definition="")],
    )
    assert not (out / "insights" / "finances" / "wage-ratio" / "index.html").exists()
    # ...but revenue, which only needs turnover, still renders.
    assert (out / "insights" / "finances" / "revenue" / "index.html").exists()


def test_capacity_urls_are_unchanged_by_the_metric_selector(tmp_path, monkeypatch):
    # Regression guard: the insights index links /insights/capacity/, and the
    # season pages were an established contract before financial metrics existed.
    out = _build_with_finances(tmp_path, monkeypatch, [_full_row("giant-fc", 2025)])
    assert (out / "insights" / "capacity" / "index.html").exists()
    assert (out / "insights" / "capacity" / season_slug(2024) / "index.html").exists()
    page = (out / "insights" / "capacity" / "index.html").read_text()
    assert "8,696 capacity" in page          # tooltip format unchanged
    assert "Stadium capacity" in page        # ...and it now offers the metric chips
    assert "Revenue" in page


def test_insights_tile_appears_when_only_an_older_season_has_data(tmp_path, monkeypatch):
    # The tile used to be gated on the current season alone, so a metric with
    # data only in earlier seasons built its pages but vanished from the index.
    out = _build_with_finances(tmp_path, monkeypatch, [_full_row("giant-fc", 2023)])
    index = (out / "insights" / "index.html").read_text()
    assert "Revenue vs. league position" in index
    assert (out / "insights" / "finances" / "revenue" / season_slug(2023) / "index.html").exists()
    assert not (out / "insights" / "finances" / "revenue" / "index.html").exists()
