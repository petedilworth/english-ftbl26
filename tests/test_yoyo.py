"""Yo-yo clubs: bounce runs, the three measures, the elastic, and the page."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import yoyo  # noqa: E402


def _h(*rows):
    """(season, tier, status) -> the five-tuple the module reads."""
    return [(s, t, st, f"Tier {t}", 10) for s, t, st in rows]


def test_a_bounce_run_alternates_in_consecutive_seasons_only():
    h = _h((2017, 2, "Relegated"), (2018, 3, "Play-off Promoted"), (2019, 2, "Relegated"),
           (2020, 3, "Promoted"), (2021, 2, "Stayed"), (2022, 2, "Relegated"), (2023, 3, "Promoted"),
           (2025, 2, "Relegated"), (2026, 3, "Promoted"))                  # 2024 missing: the gap breaks it
    runs = yoyo.bounce_runs(h)
    assert [(r["start"], r["end"], r["pattern"]) for r in runs] == [
        (2017, 2020, "RPRP"), (2022, 2023, "RP"), (2025, 2026, "RP")]
    # Two relegations in a row are a fall, not a bounce.
    assert yoyo.bounce_runs(_h((2001, 1, "Relegated"), (2002, 2, "Relegated"), (2003, 3, "Promoted"))) == [
        {"start": 2002, "end": 2003, "length": 2, "pattern": "RP"}]
    # A top-flight title is not a promotion.
    assert yoyo.bounce_runs(_h((2001, 2, "Promoted"), (2002, 1, "Champions"))) == []


def test_an_active_run_needs_the_next_season_in_progress():
    h = _h((2024, 1, "Relegated"), (2025, 2, "Promoted"), (2026, 1, "Relegated"), (2027, 2, "In progress"))
    assert yoyo.active_run(h, 2026)["length"] == 3
    assert yoyo.active_run(h[:-1], 2026) is None                      # no season under way
    assert yoyo.active_run(h, 2025) is None                           # the run ended after the "latest" season


def test_the_measures_count_finished_seasons_only():
    h = _h((2020, 2, "Relegated"), (2021, 3, "Promoted"), (2022, 2, "Stayed"), (2023, 2, "Relegated"),
           (2024, 3, "Stayed"), (2025, 3, "In progress"))
    m = yoyo.measures(h)
    assert m["seasons"] == 5 and m["moves"] == 3 and m["promotions"] == 1 and m["relegations"] == 2
    assert m["mps"] == pytest.approx(0.6) and m["amplitude"] == 1 and m["restlessness"] == pytest.approx(0.6)


def test_fastest_fall_climb_and_round_trip():
    h = _h((1990, 1, "Relegated"), (1991, 2, "Relegated"), (1992, 3, "Relegated"), (1993, 4, "Stayed"),
           (1994, 4, "Promoted"), (1995, 3, "Promoted"), (1996, 2, "Promoted"), (1997, 1, "Stayed"))
    f = yoyo.fastest(h)
    assert f["fall"] == (3, 1990, 1993) and f["climb"] == (3, 1994, 1997)
    assert yoyo.round_trip(h) == (3, 1990, 1993, 1997)               # back to where it was, 7 years later
    assert yoyo.round_trip(h[:4])[0] == 0                              # never came back


def test_the_elastic_counts_reversals_by_boundary_and_decade():
    hists = {
        "a": _h((2005, 1, "Relegated"), (2006, 2, "Promoted"), (2007, 1, "Stayed")),      # straight back up
        "b": _h((2005, 1, "Relegated"), (2006, 2, "Stayed")),                              # stuck
        "c": _h((2015, 2, "Promoted"), (2016, 1, "Relegated"), (2017, 2, "In progress")),  # straight back down
    }
    e = yoyo.elastic(hists)
    b12 = e["boundaries"][(1, 2)]
    assert b12["n"] == 4 and b12["back"] == 2 and b12["n2000"] == 3 and b12["back2010"] == 1
    # c's 2016 relegation has only a season in progress after it, so it is not yet a crossing.
    assert e["by_tier"]["relegated"][1] == {"n": 2, "n2000": 2, "back": 1, "back2000": 1}
    assert e["by_tier"]["promoted"][2]["back"] == 1


def test_assemble_ranks_only_clubs_with_enough_seasons():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_master (club_id TEXT PRIMARY KEY, canonical_name TEXT)")
    conn.execute("CREATE TABLE standings (club_id TEXT, season_end_year INT, tier INT, status TEXT,"
                 " division_name TEXT, position INT)")
    conn.executemany("INSERT INTO club_master VALUES (?,?)", [("bouncer-fc", "Bouncer FC"), ("blip-fc", "Blip FC")])
    for y in range(2000, 2027):
        st = "Relegated" if y % 2 else "Promoted"
        conn.execute("INSERT INTO standings VALUES (?,?,?,?,?,?)", ("bouncer-fc", y, 2 if y % 2 else 3, st, "D", 1))
    conn.execute("INSERT INTO standings VALUES ('bouncer-fc', 2027, 3, 'In progress', 'D', 1)")
    conn.execute("INSERT INTO standings VALUES ('blip-fc', 2026, 4, 'Relegated', 'D', 24)")   # one season, one move
    d = yoyo.assemble(conn)
    assert d["ranked_count"] == 1 and d["leaders"]["mps"][0]["club_id"] == "bouncer-fc"
    assert d["leaders"]["run"][0]["run"] == 27
    assert d["active"][0]["club_id"] == "bouncer-fc" and d["active"][0]["active"]["length"] == 27
    assert "blip-fc" not in d["shown"]


def test_the_page_builds_with_traces_and_the_elastic(tmp_path, monkeypatch):
    import shutil

    import site_build as sb
    from site_build import SiteBuilder
    from test_digest import _make_db

    disk = tmp_path / "england.db"
    src = _make_db()
    # Give Giant FC a bounce so there is a run to draw: relegated, promoted, relegated.
    for y, tier, st in ((2021, 1, "Relegated"), (2022, 2, "Promoted"), (2023, 1, "Relegated")):
        src.execute("DELETE FROM standings WHERE club_id = 'giant-fc' AND season_end_year = ?", (y,))
        src.execute("INSERT INTO standings VALUES (?, ?, 'D', 'giant-fc', 'Giant FC', 18, 38, 0, 0, 0, 0, 0, 0, 0, ?, 'test')",
                    (y, tier, st))
    src.commit()
    dst = sqlite3.connect(disk); src.backup(dst); dst.close()
    content_dir = tmp_path / "content" / "insights"
    content_dir.mkdir(parents=True)
    (content_dir / "yo-yo.md").write_text("Up and down.\n", encoding="utf-8")
    shutil.copytree(Path(__file__).parent.parent / "templates", tmp_path / "templates")
    shutil.copytree(Path(__file__).parent.parent / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(yoyo, "MIN_SEASONS", 3)
    out = tmp_path / "site"
    SiteBuilder(disk, out, charts_enabled=False).build()

    page = (out / "insights" / "yo-yo" / "index.html").read_text(encoding="utf-8")
    assert "Up and down." in page and 'id="seismograph"' in page
    assert 'class="seis-row" data-club="giant-fc"' in page and 'stroke="#eb6834"' in page   # a run, in orange
    assert "Where the elastic is" in page and "Hall of fame" in page and "The volatility league" in page
    assert (out / "insights" / "yo-yo" / "yoyo-data.js").exists()
    assert "Yo-yo clubs" in (out / "insights" / "index.html").read_text(encoding="utf-8")


def test_without_prose_the_old_table_still_builds(tmp_path, monkeypatch):
    import shutil

    import site_build as sb
    from site_build import SiteBuilder
    from test_digest import _make_db

    disk = tmp_path / "england.db"
    src = _make_db(); src.commit()
    dst = sqlite3.connect(disk); src.backup(dst); dst.close()
    (tmp_path / "content").mkdir()
    shutil.copytree(Path(__file__).parent.parent / "templates", tmp_path / "templates")
    shutil.copytree(Path(__file__).parent.parent / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "site"
    SiteBuilder(disk, out, charts_enabled=False).build()
    page = (out / "insights" / "yo-yo" / "index.html").read_text(encoding="utf-8")
    assert "Yo-yo score" in page and "seismograph" not in page
