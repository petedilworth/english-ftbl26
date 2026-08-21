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
    # exist_ok: callers may have already written content/insights/ files
    # that some pages - and the hooks linking to them - are gated on.
    content_dir.mkdir(exist_ok=True)
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
    edge_labels = re.findall(r'class="axis-label-edge"[^>]*>([\d,]+)</text>', page)
    assert len(edge_labels) == 2           # cap_min and cap_max labels
    assert all(not label.startswith("-") for label in edge_labels)

    tick_labels = re.findall(r'class="axis-label-tick"[^>]*>([\d,]+)</text>', page)
    assert all(not label.startswith("-") for label in tick_labels)


def test_scatter_y_axis_has_intermediate_ticks(tmp_path, monkeypatch):
    # The min/max labels alone were the only readable values on the axis;
    # three evenly-spaced ticks in between make the scale legible. Two
    # clubs with well-separated capacities, so padding can't coincidentally
    # collapse a tick onto an edge label the way a single data point would.
    small_story = "---\ncapacity: 2000\n---\n## Origins\nA small ground.\n"
    out = _build_with_content(
        tmp_path, monkeypatch, {"giant-fc": RICH_STORY, "steady-fc": small_story}
    )
    page = (out / "insights" / "capacity" / "index.html").read_text()
    ticks = re.findall(r'class="axis-label-tick"[^>]*>([\d,]+)</text>', page)
    assert len(ticks) == 3

    edge_min, edge_max = (
        int(v.replace(",", ""))
        for v in re.findall(r'class="axis-label-edge"[^>]*>([\d,]+)</text>', page)[::-1]
    )
    for label in ticks:
        value = int(label.replace(",", ""))
        assert edge_min < value < edge_max


def test_scatter_page_has_click_and_tier_filter_markup(tmp_path, monkeypatch):
    small_story = "---\ncapacity: 2000\n---\n## Origins\nA small ground.\n"
    out = _build_with_content(
        tmp_path, monkeypatch, {"giant-fc": RICH_STORY, "steady-fc": small_story}
    )
    page = (out / "insights" / "capacity" / "index.html").read_text()

    assert 'pointer-events="all"' in page
    assert 'tabindex="0"' in page
    assert 'role="button"' in page
    assert 'id="scatter-detail"' in page

    assert 'data-tier="all"' in page
    for tier in range(1, 6):
        assert f'data-tier="{tier}"' in page

    # "All tiers" is the only chip marked active within the tier-filter row
    # itself (the page may have other active chips, e.g. a season tab).
    tier_block = re.search(
        r'<div class="map-chips scatter-tier-chips">.*?</div>', page, re.S
    ).group(0)
    assert tier_block.count("chip-active") == 1
    all_tiers_chip = re.search(r'<button class="([^"]*)" data-tier="all">', tier_block)
    assert "chip-active" in all_tiers_chip.group(1)


def test_scatter_data_js_is_well_formed(tmp_path, monkeypatch):
    tiny_story = "---\ncapacity: 500\n---\n## Origins\nA small ground.\n"
    out = _build_with_content(tmp_path, monkeypatch, {"giant-fc": tiny_story})
    raw = (out / "insights" / "capacity" / "insight-scatter-data.js").read_text()
    prefix = "window.INSIGHT_SCATTER_DATA = "
    assert raw.startswith(prefix)
    payload = json.loads(raw[len(prefix):].rstrip("\n").rstrip(";"))

    assert payload["scale"] == "linear"
    assert payload["formatKind"] == "count"
    assert payload["points"]
    for field in (
        "id", "name", "color", "tier", "divisionName", "position",
        "overallPos", "value", "valueLabel", "tooltip",
    ):
        assert field in payload["points"][0]
        assert payload["points"][0][field] is not None


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
    # The five financial metrics share one tile on the index - they are one
    # page with chips to switch metric - and it points at a page that exists.
    index = (out / "insights" / "index.html").read_text()
    assert "Club finances" in index
    assert "finances/revenue/index.html" in index


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
    assert "Club finances" in index
    assert (out / "insights" / "finances" / "revenue" / season_slug(2023) / "index.html").exists()
    # Only the *current* season is written to the bare base URL, so for a
    # metric whose newest data is older than the current season the tile
    # must link to the season page. It used to link here regardless, which
    # was a 404 for all five finance tiles on the live site.
    assert not (out / "insights" / "finances" / "revenue" / "index.html").exists()
    assert f"finances/revenue/{season_slug(2023)}/index.html" in index


# ── Club finances on the team page ──────────────────────────────────────

def _finances_on_db(tmp_path, monkeypatch, db, rows, files=None):
    """Seed finances onto a caller-supplied db, then build the site."""
    conn = sqlite3.connect(db)
    finances.seed_club_finances(conn, _finances_csv(tmp_path, rows))
    conn.commit()
    conn.close()
    return _build_site_with_content(
        tmp_path, monkeypatch, db, files or {"giant-fc": RICH_STORY}
    )


def _l1_row(club_id, name, position, points):
    """A 2024/25 League One standings row, for division-rank fixtures."""
    return (2025, 3, "League One", club_id, name,
            position, 46, 15, 10, 21, 50, 60, -10, points, "Stayed", "test")


def test_team_page_shows_the_clubs_finances(tmp_path, monkeypatch):
    out = _build_with_finances(tmp_path, monkeypatch, [
        _full_row("giant-fc", 2025, turnover=12_000_000, staff_costs=9_000_000),
        _full_row("giant-fc", 2024),
    ])
    page = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "<h2>Finances</h2>" in page
    assert "£12.0m" in page and "£9.0m" in page   # newest season
    assert "£10.0m" in page                       # prior season
    assert season_label(2025) in page
    assert "75%" in page                          # 9.0 / 12.0 wage ratio


def test_team_page_without_finance_data_has_no_finances_section(tmp_path, monkeypatch):
    # steady-fc is in the fixture db but gets no club_finances row.
    out = _build_with_finances(tmp_path, monkeypatch, [_full_row("giant-fc", 2025)])
    page = (out / "team" / "steady-fc" / "index.html").read_text()
    assert "<h2>Finances</h2>" not in page


def test_team_page_states_non_disclosure_rather_than_showing_a_gap(tmp_path, monkeypatch):
    # The point of the disclosure column: a club that declined to publish
    # should read as a finding, not as missing data.
    out = _build_with_finances(tmp_path, monkeypatch, [
        _full_row("giant-fc", 2025, disclosure="small_company",
                  turnover="", staff_costs="", staff_costs_definition=""),
    ])
    page = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "small-company regime" in page
    assert "£" not in page.split("<h2>Finances</h2>")[1].split("<h2>")[0]


def test_finance_rank_is_measured_within_the_division(tmp_path, monkeypatch):
    db = _build_capacity_db(
        tmp_path,
        extra_clubs=[("rich-fc", "Rich FC", 3), ("poor-fc", "Poor FC", 3)],
        extra_rows=[_l1_row("rich-fc", "Rich FC", 1, 90),
                    _l1_row("poor-fc", "Poor FC", 20, 40)],
    )
    out = _finances_on_db(tmp_path, monkeypatch, db, [
        _full_row("rich-fc", 2025, turnover=30_000_000),
        _full_row("giant-fc", 2025, turnover=20_000_000),
        _full_row("poor-fc", 2025, turnover=10_000_000),
    ])
    page = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "2nd of 3" in page
    assert "2nd highest turnover of the 3 clubs with published figures" in page
    # The top of the table reads as "Highest", not "1st highest".
    rich = (out / "team" / "rich-fc" / "index.html").read_text()
    assert "Highest turnover of the 3 clubs" in rich


def test_finance_rank_denominator_counts_only_published_figures(tmp_path, monkeypatch):
    # Coverage is partial by design, so the rank must never imply that
    # every club in the division published a figure.
    db = _build_capacity_db(
        tmp_path,
        extra_clubs=[("rich-fc", "Rich FC", 3), ("poor-fc", "Poor FC", 3),
                     ("quiet-fc", "Quiet FC", 3)],
        extra_rows=[_l1_row("rich-fc", "Rich FC", 1, 90),
                    _l1_row("poor-fc", "Poor FC", 20, 40),
                    _l1_row("quiet-fc", "Quiet FC", 15, 55)],
    )
    out = _finances_on_db(tmp_path, monkeypatch, db, [
        _full_row("rich-fc", 2025, turnover=30_000_000),
        _full_row("giant-fc", 2025, turnover=20_000_000),
        _full_row("poor-fc", 2025, turnover=10_000_000),
        # In the division and filing, but with no turnover published.
        _full_row("quiet-fc", 2025, turnover=""),
    ])
    page = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "2nd of 3" in page
    assert "2nd of 4" not in page


def test_team_page_links_back_to_the_finance_charts(tmp_path, monkeypatch):
    out = _build_with_finances(tmp_path, monkeypatch, [_full_row("giant-fc", 2025)])
    page = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "insights/finances/revenue/" in page
    assert "Compare across the pyramid" in page


# ── Safe thresholds insight ──────────────────────────────────────────────

def _build_with_safe_thresholds(tmp_path, monkeypatch, db, intro_prose=None):
    """Like _build_with_insight_content, but seeds insights/safe-thresholds.md."""
    import shutil
    import site_build as sb

    content_dir = tmp_path / "content"
    (content_dir / "insights").mkdir(parents=True)
    (content_dir / "giant-fc.md").write_text(RICH_STORY, encoding="utf-8")
    if intro_prose is not None:
        (content_dir / "insights" / "safe-thresholds.md").write_text(
            intro_prose, encoding="utf-8"
        )
    real_root = Path(__file__).parent.parent
    shutil.copytree(real_root / "templates", tmp_path / "templates")
    shutil.copytree(real_root / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()
    return out


def _stayed_row(club_id, name, tier, points, played=None, season=2024):
    played = played or (38 if tier == 1 else 46)
    return (season, tier, f"Tier {tier}", club_id, name,
            10, played, 5, 5, 5, 20, 20, 0, points, "Stayed", "test")


SAFE_THRESHOLDS_INTRO = "The magic number for staying up, in theory and in practice."


def test_safe_thresholds_intro_renders_the_full_paragraph(tmp_path, monkeypatch):
    # Regression for a real bug: an earlier version indexed into the intro
    # string instead of using it directly, so the page showed a single
    # character instead of the paragraph.
    db = _build_capacity_db(tmp_path)
    out = _build_with_safe_thresholds(tmp_path, monkeypatch, db, SAFE_THRESHOLDS_INTRO)
    page = (out / "insights" / "safe-thresholds" / "index.html").read_text()
    assert SAFE_THRESHOLDS_INTRO in page


def test_insights_index_has_exactly_one_safe_thresholds_tile(tmp_path, monkeypatch):
    # Regression: an earlier version listed the tile unconditionally *and*
    # conditionally, so it appeared twice whenever the content file existed.
    db = _build_capacity_db(tmp_path)
    out = _build_with_safe_thresholds(tmp_path, monkeypatch, db, SAFE_THRESHOLDS_INTRO)
    index = (out / "insights" / "index.html").read_text()
    assert index.count("Safe thresholds") == 1


def test_safe_thresholds_absent_without_content_file(tmp_path, monkeypatch):
    db = _build_capacity_db(tmp_path)
    out = _build_with_safe_thresholds(tmp_path, monkeypatch, db, intro_prose=None)
    assert not (out / "insights" / "safe-thresholds" / "index.html").exists()
    assert "Safe thresholds" not in (out / "insights" / "index.html").read_text()


def test_records_page_renders_only_once(tmp_path, monkeypatch):
    # Regression: an earlier version duplicated the whole method body, so
    # records/index.html was built (harmlessly but wastefully) twice.
    db = _build_capacity_db(tmp_path)
    out = _build_with_safe_thresholds(tmp_path, monkeypatch, db, intro_prose=None)
    page = (out / "insights" / "records" / "index.html").read_text()
    assert page.count("<h1>Records") == 1


def test_safe_thresholds_shows_games_played_per_row(tmp_path, monkeypatch):
    db = _build_capacity_db(
        tmp_path,
        extra_clubs=[("shortseason-fc", "Shortseason FC", 1)],
        extra_rows=[_stayed_row("shortseason-fc", "Shortseason FC", 1, points=20, played=33)],
    )
    out = _build_with_safe_thresholds(tmp_path, monkeypatch, db, SAFE_THRESHOLDS_INTRO)
    page = (out / "insights" / "safe-thresholds" / "index.html").read_text()
    assert "Played" in page
    # The low points total sits directly next to its games-played count, so
    # a reader can see the season was short rather than a genuine record.
    row = re.search(r"<tr>\s*<td[^>]*>.*?Shortseason.*?</tr>", page, re.S).group(0)
    assert re.search(r">\s*33\s*<", row)


def test_safe_thresholds_groups_rows_by_division_not_just_points(tmp_path, monkeypatch):
    # Two tier-1 clubs with higher points than two tier-3 clubs. A pure
    # points-ascending sort would interleave the tiers (tier-3's 10/15
    # ahead of tier-1's 20/25); grouped by division, both tier-1 rows must
    # come first despite their higher points.
    db = _build_capacity_db(
        tmp_path,
        extra_clubs=[
            ("top-low-fc", "Top Low FC", 1), ("top-high-fc", "Top High FC", 1),
            ("low-low-fc", "Low Low FC", 3), ("low-high-fc", "Low High FC", 3),
        ],
        extra_rows=[
            _stayed_row("top-low-fc", "Top Low FC", 1, points=20),
            _stayed_row("top-high-fc", "Top High FC", 1, points=25),
            _stayed_row("low-low-fc", "Low Low FC", 3, points=10),
            _stayed_row("low-high-fc", "Low High FC", 3, points=15),
        ],
    )
    out = _build_with_safe_thresholds(tmp_path, monkeypatch, db, SAFE_THRESHOLDS_INTRO)
    page = (out / "insights" / "safe-thresholds" / "index.html").read_text()

    names_in_order = [
        m.group(1) for m in re.finditer(
            r'href="[^"]*/team/(?:top|low)-[a-z]+-fc/index\.html">([^<]+)<', page
        )
    ]
    assert names_in_order == ["Top Low FC", "Top High FC", "Low Low FC", "Low High FC"], (
        "expected both tier-1 rows before both tier-3 rows, "
        "each internally still ordered by ascending points"
    )


# ── The front door: home page scale bar, hooks and club search ───────────

SAFE_THRESHOLDS_MD = "The magic number for survival is not one number at all.\n"


def _front_door(tmp_path, monkeypatch, rows=None, insights=None):
    """
    Build the site and return (out, home html). `rows` seeds club_finances;
    `insights` writes content/insights/<name>.md, which some pages - and so
    some hooks, which must never link to a page that wasn't built - are
    gated on.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = _db_on_disk(tmp_path)
    if rows:
        conn = sqlite3.connect(db)
        finances.seed_club_finances(conn, _finances_csv(tmp_path, rows))
        conn.commit()
        conn.close()
    if insights:
        target = tmp_path / "content" / "insights"
        target.mkdir(parents=True)
        for name, text in insights.items():
            (target / f"{name}.md").write_text(text, encoding="utf-8")
    out = _build_site_with_content(
        tmp_path, monkeypatch, db, {"giant-fc": RICH_STORY}
    )
    return out, (out / "index.html").read_text()


def _hooks(home):
    return re.findall(
        r'class="tile hook" href="([^"]+)">\s*<span class="hook-text">([^<]*)</span>',
        home,
    )


def test_home_scale_bar_counts_reachable_things(tmp_path, monkeypatch):
    out, home = _front_door(tmp_path, monkeypatch)
    # The club count must agree with the number of team pages that exist and
    # with the teams index. The live database has one club in club_master
    # with no trajectory row and so no page, which is how home came to
    # advertise 162 clubs while the teams index said 161.
    pages = len(list((out / "team").iterdir()))
    assert f'stat-value">{pages}</div><div class="stat-label">clubs<' in home
    assert f"{pages} clubs to have played" in (out / "teams" / "index.html").read_text()
    # Every club count the page states must be the same number - the scale
    # bar, the search placeholder, the browse-all link and the Teams tile.
    assert f"Search {pages} clubs" in home
    assert f"browse all {pages} clubs" in home
    assert f"{pages} clubs, each with a page" in home


def test_home_scale_bar_drops_a_count_that_is_zero(tmp_path, monkeypatch):
    # No finances seeded, so there are no club-season accounts to boast of.
    # An empty shelf should say nothing rather than advertise a 0.
    _, home = _front_door(tmp_path, monkeypatch)
    assert "club-season accounts" not in home
    assert '<div class="stat-value">0</div>' not in home


def test_home_hooks_carry_a_number_and_a_link_that_resolves(tmp_path, monkeypatch):
    out, home = _front_door(
        tmp_path, monkeypatch,
        rows=[_full_row("giant-fc", 2025, profit_before_tax=-5_000_000)],
        insights={"safe-thresholds": SAFE_THRESHOLDS_MD},
    )
    hooks = _hooks(home)
    assert hooks, "expected at least one story hook on the home page"
    for href, text in hooks:
        assert re.search(r"\d", text), f"hook has no number in it: {text!r}"
        assert "None" not in text, f"unformatted None leaked into a hook: {text!r}"
        assert (out / href.removeprefix("./")).exists(), f"hook links nowhere: {href}"


def test_home_hooks_survive_without_any_finance_data(tmp_path, monkeypatch):
    # Three of the four recipes read club_finances. A database without that
    # table should still get a hook out of club_trajectory alone - not an
    # empty section, and not a traceback. The fixture's clubs are all tier 3,
    # so give one the top-flight run the surviving fallback looks for.
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = _db_on_disk(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE club_trajectory SET current_tier = 1, current_tier_streak = 20"
        " WHERE club_id = 'steady-fc'"
    )
    conn.commit()
    conn.close()
    out = _build_site_with_content(
        tmp_path, monkeypatch, db, {"giant-fc": RICH_STORY}
    )
    home = (out / "index.html").read_text()
    hooks = _hooks(home)
    assert hooks, "expected a hook from the non-financial fallback"
    for href, _ in hooks:
        assert (out / href.removeprefix("./")).exists()


def test_home_hooks_never_link_to_a_page_that_was_not_built(tmp_path, monkeypatch):
    # Without the safe-thresholds content file that page isn't built, so the
    # hook that would point at it must not be offered either.
    _, home = _front_door(tmp_path, monkeypatch)
    assert "safe-thresholds" not in home


def test_home_build_is_byte_identical_twice(tmp_path, monkeypatch):
    # Guards against anyone making the hook rotation random later: a deploy
    # you can't diff is a deploy you can't review.
    rows = [_full_row("giant-fc", 2025, profit_before_tax=-5_000_000)]
    first = _front_door(tmp_path / "a", monkeypatch, rows=rows)[1]
    second = _front_door(tmp_path / "b", monkeypatch, rows=rows)[1]
    assert first == second


def test_home_club_search_is_present_but_closed_until_typed(tmp_path, monkeypatch):
    out, home = _front_door(tmp_path, monkeypatch)
    assert 'id="home-search"' in home
    # The list ships with the page so results are instant, but the page must
    # not open with every club on screen.
    assert 'id="home-results" hidden' in home
    assert home.count('data-name="') == len(list((out / "team").iterdir()))


def test_home_names_an_early_season_rather_than_looking_broken(tmp_path, monkeypatch):
    # The newest season enters the database with its first results, so home
    # can show one division of P1 rows for weeks. Say so on the page.
    db = _db_on_disk(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO standings (season_end_year, tier, division_name, club_id,
            club_name, position, played, won, drawn, lost, gf, ga, gd,
            points, status, source)
        VALUES (2026, 5, 'National League', 'giant-fc', 'Giant FC',
                1, 1, 1, 0, 0, 3, 0, 3, 3, 'In progress', 'test')
        """
    )
    conn.commit()
    conn.close()
    out = _build_site_with_content(tmp_path, monkeypatch, db, {"giant-fc": RICH_STORY})
    home = (out / "index.html").read_text()
    assert "has kicked off" in home
    assert "1 game in" in home


def test_insights_index_groups_and_has_no_duplicate_targets(tmp_path, monkeypatch):
    out = _build_with_finances(tmp_path, monkeypatch, [_full_row("giant-fc", 2025)])
    index = (out / "insights" / "index.html").read_text()
    assert "Interactive charts" in index and "Stories" in index
    paths = re.findall(r'class="tile" href="([^"]+)"', index)
    assert len(paths) == len(set(paths)), "duplicate tiles on the insights index"
    # One tile for all five financial metrics, not five.
    assert sum(1 for p in paths if "finances/" in p) == 1
    for path in paths:
        assert (out / "insights" / path.removeprefix("../insights/")).exists(), path
