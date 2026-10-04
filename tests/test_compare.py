"""Two clubs side by side: the figures, how they rank, and the pages."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import compare  # noqa: E402


def test_standing_puts_ties_at_the_lower_place_so_nothing_draws_no_bar():
    s = compare.standing({"a": 0, "b": 0, "c": 0, "d": 5, "e": None})
    assert s["a"] == s["b"] == s["c"] == 0.0      # no titles: no bar, not half a bar
    assert s["d"] == 1.0 and s["e"] is None
    low = compare.standing({"a": 1, "b": 4}, higher_is_better=False)   # tier 1 beats tier 4
    assert low == {"a": 1.0, "b": 0.0}


def test_form_points_needs_the_full_run():
    ms = [["2026-09-01", "x", "X", "H", 2, 0], ["", "", "", "A", 1, 1], ["", "", "", "H", 0, 3],
          ["", "", "", "A", 1, 0], ["", "", "", "H", 2, 2]]
    assert compare.form_points(ms) == 3 + 1 + 0 + 3 + 1
    assert compare.form_points(ms[:3]) is None


def test_same_division_matches_on_the_division_not_just_the_tier():
    a = [[2020, 3, 50, 4, "League One", "Stayed"], [2021, 3, 52, 6, "League One", "Stayed"]]
    b = [[2020, 3, 60, 14, "League One", "Stayed"], [2021, 3, 70, 1, "Other Division", "Stayed"]]
    assert compare.same_division(a, b) == [
        {"season": 2020, "division": "League One", "a": 4, "b": 14, "live": False}]


def test_history_places_a_club_in_the_whole_pyramid():
    from test_digest import _make_db
    hist = compare.history(_make_db())
    for rows in hist.values():
        for season, tier, place, pos, *_ in rows:
            assert place >= pos            # every club above in the tiers above counts too
            if tier == 1:
                assert place == pos


def test_miles_between_grounds():
    assert compare.miles(52.59, -1.97, 52.59, -2.13) == pytest.approx(6.7, abs=0.2)  # Bescot to Molineux
    assert compare.miles(None, 0, 1, 1) is None


def test_the_pages_build_with_club_files_fixtures_and_links(tmp_path, monkeypatch):
    import shutil

    import site_build as sb
    from site_build import SiteBuilder
    from test_digest import _fixture, _make_db

    disk = tmp_path / "england.db"
    src = _make_db()
    src.commit()
    dst = sqlite3.connect(disk); src.backup(dst); dst.close()
    shutil.copytree(Path(__file__).parent.parent / "templates", tmp_path / "templates")
    shutil.copytree(Path(__file__).parent.parent / "static", tmp_path / "static")
    (tmp_path / "content").mkdir()
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "site"
    SiteBuilder(disk, out, charts_enabled=False, fixtures=[_fixture()]).build()

    page = (out / "compare" / "index.html").read_text(encoding="utf-8")
    assert 'id="cmp-a"' in page and 'id="cmp-b"' in page and "Tale of the tape" in page
    assert '<option value="Giant FC">' in page
    assert 'href="#a=giant-fc&amp;b=steady-fc"' in page or 'href="#a=giant-fc&b=steady-fc"' in page

    index = (out / "compare" / "compare-index.js").read_text(encoding="utf-8")
    data = json.loads(index[index.index("=") + 1:].rstrip(";"))
    assert {c["id"] for c in data["clubs"]} >= {"giant-fc", "steady-fc"}
    assert [t[0] for t in data["tape"]] == [t[0] for t in compare.TAPE]
    assert data["fixtures"][0]["home_id"] == "giant-fc"

    club = (out / "compare" / "club" / "giant-fc.js").read_text(encoding="utf-8")
    d = json.loads(club[club.index("] = ") + 4:].rstrip(";"))
    assert d["name"] == "Giant FC" and d["history"] and set(d["pct"]) == {t[0] for t in compare.TAPE}

    fixtures = (out / "fixtures" / "index.html").read_text(encoding="utf-8")
    assert "Giant FC" in fixtures and "compare/index.html#a=giant-fc" in fixtures

    team = (out / "team" / "giant-fc" / "index.html").read_text(encoding="utf-8")
    assert "Compare Giant FC" in team and "compare/index.html#a=giant-fc&b=steady-fc" in team.replace("&amp;", "&")
    assert 'data-club-id="giant-fc"' in team or "h2h-table" not in team

    base = (out / "index.html").read_text(encoding="utf-8")
    assert "compare/index.html" in base and "fixtures/index.html" in base


def test_no_fixtures_still_builds_both_pages(tmp_path, monkeypatch):
    import shutil

    import site_build as sb
    from site_build import SiteBuilder
    from test_digest import _make_db

    disk = tmp_path / "england.db"
    src = _make_db()
    src.commit()
    dst = sqlite3.connect(disk); src.backup(dst); dst.close()
    shutil.copytree(Path(__file__).parent.parent / "templates", tmp_path / "templates")
    shutil.copytree(Path(__file__).parent.parent / "static", tmp_path / "static")
    (tmp_path / "content").mkdir()
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "site"
    SiteBuilder(disk, out, charts_enabled=False).build()
    assert "could not be fetched" in (out / "fixtures" / "index.html").read_text(encoding="utf-8")
    assert "cmp-fixtures" not in (out / "compare" / "index.html").read_text(encoding="utf-8")
