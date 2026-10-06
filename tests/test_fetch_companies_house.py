"""The Companies House fetch, against a fake register shaped like the real API."""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import fetch_companies_house as fch  # noqa: E402


class Resp:
    def __init__(self, code, body=None):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


class FakeSession:
    """Answers by path. A missing path is a 404, as the real API does."""

    def __init__(self, pages):
        self.pages, self.headers, self.seen = pages, {}, []

    def get(self, url, params=None, timeout=None):
        path = url.replace(fch.API, "")
        self.seen.append((path, dict(params or {})))
        hit = self.pages.get(path)
        if callable(hit):
            hit = hit(params or {})
        if isinstance(hit, Resp):
            return hit
        return Resp(200, hit) if hit is not None else Resp(404)

    def post(self, url, json=None, timeout=None):
        coords = {"N5 1BU": (51.555, -0.108), "SW6 1HS": (51.481, -0.191), "M1 1AA": (53.48, -2.24)}
        return Resp(200, {"result": [{"query": p, "result": ({"latitude": coords[p][0], "longitude": coords[p][1]}
                                                              if p in coords else None)} for p in json["postcodes"]]})


def reg(pages):
    return fch.Register("not-a-real-key", FakeSession(pages), delay=0)


def test_the_key_goes_in_basic_auth_and_is_never_the_only_thing_logged():
    r = reg({})
    assert r.s.headers["Authorization"].startswith("Basic ")
    assert "not-a-real-key" not in r.s.headers["Authorization"]       # encoded, not plain


def test_a_refused_key_stops_the_run_and_a_missing_record_is_none(monkeypatch):
    monkeypatch.setattr(fch.time, "sleep", lambda s: None)
    assert reg({}).get("/company/00000001") is None
    with pytest.raises(SystemExit, match="refused the key"):
        reg({"/company/1": Resp(401)}).get("/company/1")
    flaky = iter([Resp(429), Resp(500), Resp(200, {"ok": 1})])
    assert reg({"/company/2": lambda p: next(flaky)}).get("/company/2") == {"ok": 1}


def test_items_pages_until_the_total():
    def officers(p):
        start = p["start_index"]
        return {"total_results": 150, "items": [{"name": f"O{i}"} for i in range(start, min(start + 100, 150))]}
    assert len(reg({"/company/1/officers": officers}).items("/company/1/officers")) == 150


CLUB = {"name": "Chelsea", "coords": (51.4817, -0.191), "ground": "Stamford Bridge", "owner": "BlueCo 22 Limited"}


def test_evidence_finds_the_ground_the_owner_and_the_parent():
    ev = {"charges": [{"particulars": {"description": "Freehold land known as Stamford Bridge stadium"}}],
          "psc": [{"name": "Chelsea FC Holdings Limited", "identification": {"registration_number": "12345678"}}],
          "officers": [{"name": "BLUECO 22 LIMITED"}], "profile": {}}
    pts, why, parent = fch.evidence(ev, CLUB, (51.481, -0.191), {"12345678"})
    assert pts == 40 + 60 + 50 + 30 and parent == "12345678"
    assert "a charge names the ground" in why and "subsidiary of another candidate" in why
    far, why_far, _ = fch.evidence({"profile": {"accounts": {"last_accounts": {"type": "dormant"}}}}, CLUB,
                                   (53.48, -2.24), set())
    assert far == -25 - 30 and "files dormant accounts" in why_far


def test_decide_takes_the_operating_club_under_its_holding_company():
    scored = [{"company_number": "12345678", "entity_name": "CHELSEA FC HOLDINGS LIMITED", "score": 116},
              {"company_number": "01234567", "entity_name": "CHELSEA FOOTBALL CLUB LIMITED", "score": 112},
              {"company_number": "99999999", "entity_name": "CHELSEA FLOWER SHOW LIMITED", "score": 69}]
    evid = {"12345678": {"profile": {"company_status": "active"}},
            "01234567": {"profile": {"company_status": "active"},
                         "psc": [{"name": "Chelsea FC Holdings", "identification": {"registration_number": "12345678"}}],
                         "charges": [{"particulars": {"description": "Stamford Bridge"}}]},
            "99999999": {"profile": {"company_status": "dissolved"}}}
    d = fch.decide(CLUB, scored, evid, {"01234567": (51.481, -0.191), "12345678": (51.48, -0.19)})
    assert d["state"] == "auto" and d["number"] == "01234567"


def test_decide_leaves_noise_unmatched():
    scored = [{"company_number": "1", "entity_name": "CHESTER HORSE DRIVING TRIALS LTD", "score": 69},
              {"company_number": "2", "entity_name": "CHESTER TRIATHLON CLUB", "score": 69}]
    d = fch.decide({"name": "Chester City", "coords": (53.19, -2.89)}, scored,
                   {"1": {"profile": {"company_status": "active"}}, "2": {"profile": {"company_status": "active"}}}, {})
    assert d["state"] == "unmatched" and "no evidence" in d["why"]


def test_snapshot_follows_the_controller_up_through_uk_companies():
    pages = {
        "/company/00109244": {"company_name": "THE ARSENAL FOOTBALL CLUB LIMITED", "company_status": "active",
                              "accounts": {"overdue": False, "next_due": "2027-02-28",
                                           "last_accounts": {"made_up_to": "2026-05-31", "type": "full"}},
                              "has_insolvency_history": False, "registered_office_address": {"postal_code": "N5 1BU"}},
        "/company/00109244/officers": {"total_results": 1, "items": [{"name": "SMITH, Ann", "officer_role": "director",
                                                                      "appointed_on": "2020-01-01"}]},
        "/company/00109244/persons-with-significant-control": {"total_results": 1, "items": [
            {"name": "Arsenal Holdings Limited", "kind": "corporate-entity-person-with-significant-control",
             "natures_of_control": ["ownership-of-shares-75-to-100-percent"],
             "identification": {"registration_number": "4250459", "country_registered": "England"}}]},
        "/company/00109244/charges": {"total_count": 1, "items": [
            {"status": "outstanding", "created_on": "2019-08-01", "persons_entitled": [{"name": "Barclays Bank PLC"}],
             "particulars": {"description": "Emirates Stadium"}}]},
        "/company/00109244/filing-history": {"total_count": 1, "items": [{"date": "2026-08-01", "type": "AA",
                                                                          "description_values": {"made_up_date": "2026-05-31"}}]},
        "/company/04250459": {"company_name": "ARSENAL HOLDINGS LIMITED", "company_status": "active"},
        "/company/04250459/persons-with-significant-control": {"total_results": 1, "items": [
            {"name": "Kse Uk Inc", "kind": "corporate-entity-person-with-significant-control",
             "identification": {"registration_number": "5173", "country_registered": "Delaware"}}]},
    }
    snap = fch.snapshot(reg(pages), "00109244")
    assert snap["accounts"]["last_type"] == "full" and not snap["accounts"]["overdue"]
    assert snap["charges"][0]["lenders"] == ["Barclays Bank PLC"]
    assert [c["name"] for c in snap["chain"]] == ["ARSENAL HOLDINGS LIMITED"]       # stops at Delaware
    assert snap["chain"][0]["psc"][0]["country"] == "Delaware"
    assert snap["filings"][0]["made_up_to"] == "2026-05-31"


def test_a_run_matches_a_reviewed_club_from_the_file(monkeypatch):
    monkeypatch.setattr(fch.time, "sleep", lambda s: None)
    conn = sqlite3.connect(ROOT / "data" / "db" / "england.db")
    pages = {"/company/04250459": {"company_name": "ARSENAL HOLDINGS LIMITED", "company_status": "active"}}
    res = fch.run(reg(pages), conn, only={"arsenal-fc"}, pc_session=FakeSession({}))
    assert res["clubs"]["arsenal-fc"]["match"] == "reviewed"
    assert res["clubs"]["arsenal-fc"]["company"]["name"] == "ARSENAL HOLDINGS LIMITED"


def test_a_run_settles_a_review_club_on_register_evidence(monkeypatch):
    monkeypatch.setattr(fch.time, "sleep", lambda s: None)
    conn = sqlite3.connect(ROOT / "data" / "db" / "england.db")
    hits = {"items": [
        {"company_number": "12345678", "company_name": "CHELSEA FC HOLDINGS LIMITED", "company_status": "active",
         "sic_codes": ["93120"]},
        {"company_number": "01234567", "company_name": "CHELSEA FOOTBALL CLUB LIMITED", "company_status": "active",
         "sic_codes": ["93120"]}]}
    pages = {
        "/search/companies": hits, "/advanced-search/companies": hits,
        "/company/12345678": {"company_name": "CHELSEA FC HOLDINGS LIMITED", "company_status": "active",
                              "registered_office_address": {"postal_code": "SW6 1HS"}},
        "/company/01234567": {"company_name": "CHELSEA FOOTBALL CLUB LIMITED", "company_status": "active",
                              "registered_office_address": {"postal_code": "SW6 1HS"}},
        "/company/01234567/persons-with-significant-control": {"total_results": 1, "items": [
            {"name": "Chelsea FC Holdings Limited", "kind": "corporate-entity-person-with-significant-control",
             "identification": {"registration_number": "12345678", "country_registered": "England"}}]},
    }
    res = fch.run(reg(pages), conn, only={"chelsea-fc"}, pc_session=FakeSession({}))
    assert "chelsea-fc" in res["clubs"], res["unmatched"]
    got = res["clubs"]["chelsea-fc"]
    assert got["match"] == "auto" and got["company"]["number"] == "01234567"
    assert got["company"]["chain"][0]["name"] == "CHELSEA FC HOLDINGS LIMITED"


def test_uk_is_recognised_however_the_register_spells_it():
    for place in ("England", "United Kingdom (England)", "U.K.", "Companies House, Cardiff", "Wales"):
        assert fch.is_uk(place), place
    for place in ("Delaware", "Cayman Islands", "Isle Of Man", None, ""):
        assert not fch.is_uk(place), place


def test_nearness_alone_never_matches_a_company_that_is_not_a_football_club():
    scored = [{"company_number": "1", "entity_name": "GRIMSBY AND CLEETHORPES YACHT CLUB LIMITED", "score": 69}]
    d = fch.decide({"name": "Cleethorpes Town", "coords": (53.56, -0.03)}, scored,
                   {"1": {"profile": {"company_status": "active"}}}, {"1": (53.56, -0.03)})
    assert d["state"] == "unmatched"
    scored = [{"company_number": "2", "entity_name": "QUORN FC LEISURE LTD", "score": 62}]
    d = fch.decide({"name": "Quorn", "coords": (52.74, -1.17)}, scored,
                   {"2": {"profile": {"company_status": "active"}}}, {"2": (52.74, -1.17)})
    assert d["state"] == "auto"
