"""Behind the club: control, charges, directors, warnings, and the page."""

import datetime
import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import companies as co  # noqa: E402


def test_the_controller_is_the_furthest_the_register_reaches():
    company = {"name": "BIG FC LTD",
               "psc": [{"name": "Big Holdings Ltd", "kind": "corporate-entity",
                        "natures": ["ownership-of-shares-75-to-100-percent"], "country": "United Kingdom (England)"}],
               "chain": [{"name": "BIG HOLDINGS LTD", "psc": [
                   {"name": "Ms Small", "kind": "individual", "natures": ["ownership-of-shares-25-to-50-percent"],
                    "residence": "England"},
                   {"name": "Mr Big", "kind": "individual", "natures": ["ownership-of-shares-50-to-75-percent"],
                    "residence": "United States"}]}]}
    c = co.controller(company)
    assert c["name"] == "Mr Big" and c["category"] == "person abroad" and c["band"] == "50–75%"
    assert c["via"] == ["BIG HOLDINGS LTD"] and c["others"] == 1


def test_controller_categories_read_the_register_as_it_is_written():
    def ctl(**p):
        return co.controller({"name": "X", "psc": [dict({"kind": "corporate-entity", "natures": []}, **p)]})["category"]
    assert ctl(name="W. W. (1990) Limited") == "company in the UK"               # no country, UK form
    assert ctl(name="Portman Holdings, Llc") == "company, country not stated"
    assert ctl(name="Woking Borough Council", kind="legal-person") == "council or public body"
    assert ctl(name="Kse Uk Inc", country="Delaware") == "company abroad"
    assert ctl(name="Blades Leisure Limited", country="U.K.") == "company in the UK"
    assert co.controller({"name": "X", "psc": []})["category"] == "no single controller"


def test_charges_directors_and_warnings():
    company = {
        "charges": [{"status": "outstanding", "created": "2024-01-01", "lenders": ["Bank A", "Fund B"],
                     "particulars": "Freehold land known as The Ground"},
                    {"status": "fully-satisfied", "created": "2001-01-01", "lenders": ["Bank C"]}],
        "officers": [{"role": "director", "appointed": "2010-01-01"},
                     {"role": "director", "appointed": "2023-01-01", "resigned": "2024-06-01"},
                     {"role": "director", "appointed": "2024-07-01", "residence": "Germany"},
                     {"role": "secretary", "appointed": "2024-01-01"}],
        "accounts": {"overdue": True, "last_type": "micro-entity"}, "insolvency": [{"type": "cva"}],
        "status": "active"}
    ch = co.charges(company)
    assert ch["outstanding"] == 1 and ch["satisfied"] == 1 and ch["lenders"] == ["Bank A", "Fund B"] and ch["property"]
    dr = co.directors(company, today=datetime.date(2026, 10, 1))
    assert (dr["now"], dr["appointed"], dr["resigned"], dr["abroad"]) == (2, 2, 1, 1)
    assert dr["churn"] == 0.6 and dr["longest_since"] == "2010-01-01"
    assert co.warnings(company) == ["accounts overdue", "insolvency history", "files micro-entity accounts"]


def test_an_automatic_match_on_nearness_alone_needs_a_football_name():
    near = "registered office 1 miles from the ground (score 109, lead 40)"
    assert not co.trusted({"match": "auto", "why": near, "company": {"name": "GRIMSBY AND CLEETHORPES YACHT CLUB"}})
    assert co.trusted({"match": "auto", "why": near, "company": {"name": "QUORN FC LEISURE LTD"}})
    assert not co.trusted({"match": "auto", "why": near, "company": {"name": "LEIGHTON BUZZARD SPORTS ASSOCIATION"}})
    assert co.trusted({"match": "auto", "why": "a charge names the ground", "company": {"name": "CHESHUNT SPORTS"}})
    assert co.trusted({"match": "reviewed", "why": "", "company": {"name": "ANYTHING"}})


def _snapshot(path):
    clubs = {
        "giant-fc": {"match": "reviewed", "why": "", "company": {
            "name": "GIANT FC LIMITED", "number": "00000001", "status": "active",
            "accounts": {"last_type": "full", "overdue": False}, "officers": [], "chain": [], "insolvency": [],
            "psc": [{"name": "Mr Far", "kind": "individual", "natures": ["ownership-of-shares-75-to-100-percent"],
                     "residence": "United States"}],
            "charges": [{"status": "outstanding", "created": "2025-01-01", "lenders": ["Lender One"],
                         "particulars": "the stadium"}]}},
        "steady-fc": {"match": "auto", "why": "a charge names the ground", "company": {
            "name": "STEADY FC LIMITED", "number": "00000002", "status": "active",
            "accounts": {"last_type": "micro-entity"}, "officers": [], "chain": [], "insolvency": [],
            "psc": [], "charges": [{"status": "outstanding", "lenders": ["Lender One"]}]}},
    }
    path.write_text(json.dumps({"fetched": "2026-10-06", "clubs": clubs,
                                "unmatched": {"lost-fc": {"name": "Lost", "tier": 7, "why": "no active candidate"}}}))
    return path


def test_the_page_builds(tmp_path, monkeypatch):
    import site_build as sb
    from site_build import SiteBuilder
    from test_digest import _make_db

    full = _make_db()
    disk = tmp_path / "england.db"
    dst = sqlite3.connect(disk); full.backup(dst); dst.close()
    (tmp_path / "data").mkdir()
    _snapshot(tmp_path / "data" / "companies_house.json")
    content_dir = tmp_path / "content" / "insights"
    content_dir.mkdir(parents=True)
    (content_dir / "behind-the-club.md").write_text("Follow the paper.\n", encoding="utf-8")
    shutil.copytree(Path(__file__).parent.parent / "templates", tmp_path / "templates")
    shutil.copytree(Path(__file__).parent.parent / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "site"
    SiteBuilder(disk, out, charts_enabled=False).build()

    page = (out / "insights" / "behind-the-club" / "index.html").read_text(encoding="utf-8")
    assert "Follow the paper." in page
    for heading in ("Who controls the club", "Borrowed against the club", "Boardroom churn", "Warning lights",
                    "Every club", "not covered"):
        assert heading in page
    assert "Mr Far" in page and "Lender One" in page and "Lost" in page
    assert "find-and-update.company-information.service.gov.uk/company/00000001" in page
    assert "Behind the club" in (out / "insights" / "index.html").read_text(encoding="utf-8")
