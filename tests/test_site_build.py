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


def test_capacity_insight_excludes_a_club_outside_the_current_season(tmp_path, monkeypatch):
    # A club whose story has capacity but who last appeared in an older
    # season (not the current one) must not be plotted against this
    # season's tier-boundary lines - see the comment in _capacity_points.
    old_season_story = """---
founded: 1990
capacity: 5000
---
## Origins
Test club with a stale standings record.
"""
    import shutil
    import site_build as sb

    db = _db_on_disk(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO club_master VALUES ('stale-fc','Stale FC',NULL,NULL,5)"
    )
    conn.execute(
        "INSERT INTO standings VALUES (2020,5,'National League','stale-fc','Stale FC',"
        "10,46,15,10,21,50,60,-10,55,'Stayed','test')"
    )
    trajectory.rebuild_trajectory(conn)
    conn.commit()
    conn.close()

    content_dir = tmp_path / "content"
    content_dir.mkdir()
    (content_dir / "giant-fc.md").write_text(RICH_STORY, encoding="utf-8")
    (content_dir / "stale-fc.md").write_text(old_season_story, encoding="utf-8")
    real_root = Path(__file__).parent.parent
    shutil.copytree(real_root / "templates", tmp_path / "templates")
    shutil.copytree(real_root / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)

    out = tmp_path / "site"
    SiteBuilder(db, out, charts_enabled=False).build()
    page = (out / "insights" / "capacity" / "index.html").read_text()
    assert page.count("<circle") == 1  # giant-fc only, not stale-fc


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
