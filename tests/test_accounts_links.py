"""
Links from a team page to the accounts a club filed.

What is pinned: every link is built from the transaction id Companies
House's own filing history gives, never guessed; a season's row links
only the filing by the company that row is about; and nothing is linked
for a club with no matched company.
"""
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

import finances                                          # noqa: E402
import parse_club_accounts as pca                        # noqa: E402
from site_build import SiteBuilder                       # noqa: E402
from test_site_build import _build_with_finances, _db_on_disk, _full_row   # noqa: E402

SITE = finances.CH_SITE


def _history(tmp_path, club="giant-fc", number="01234567"):
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "mapping.json").write_text(json.dumps({club: {"company_number": number,
                                                          "entity_name": "Giant FC Ltd"}}))
    (docs / f"{club}__filings.json").write_text(json.dumps({"items": [
        {"type": "AA01", "description": "change-account-reference-date", "date": "2026-04-01",
         "transaction_id": "NOTICE", "links": {"document_metadata": "https://d/document/N",
                                               "self": f"/company/{number}/filing-history/NOTICE"}},
        {"type": "AA", "description": "accounts-with-accounts-type-full", "date": "2026-03-27",
         "transaction_id": "TXN2025", "paper_filed": True, "pages": 38,
         "description_values": {"made_up_date": "2025-06-30"},
         "links": {"document_metadata": "https://d/document/DOC2025",
                   "self": f"/company/{number}/filing-history/TXN2025"}},
        {"type": "AA", "description": "accounts-with-accounts-type-full", "date": "2025-03-20",
         "transaction_id": "TXN2024", "description_values": {"made_up_date": "2024-06-30"},
         "links": {"document_metadata": "https://d/document/DOC2024",
                   "self": f"/company/{number}/filing-history/TXN2024"}},
    ]}))
    (docs / f"{club}__1.pdf").write_bytes(b"%PDF")
    (docs / f"{club}__2.xhtml").write_bytes(b"<html/>")
    return docs


# ── the index ──────────────────────────────────────────────────────────────

def test_the_index_lists_every_accounts_filing_and_skips_the_notices(tmp_path):
    index = tmp_path / "filings.tsv"
    assert pca.write_filings_index(_history(tmp_path), index) == 2
    rows = finances.load_filings(index)["giant-fc"]
    assert [r["transaction_id"] for r in rows] == ["TXN2025", "TXN2024"]
    assert rows[0]["made_up_date"] == "2025-06-30" and rows[0]["paper_filed"] == "yes"
    assert rows[0]["format"] == "pdf" and rows[1]["format"] == "xhtml"
    assert rows[0]["company_number"] == "01234567"


def test_the_transaction_id_falls_back_to_the_filing_s_own_link(tmp_path):
    docs = _history(tmp_path)
    data = json.loads((docs / "giant-fc__filings.json").read_text())
    del data["items"][1]["transaction_id"]
    (docs / "giant-fc__filings.json").write_text(json.dumps(data))
    index = tmp_path / "filings.tsv"
    pca.write_filings_index(docs, index)
    assert finances.load_filings(index)["giant-fc"][0]["transaction_id"] == "TXN2025"


def test_a_partial_run_keeps_the_other_clubs_filings(tmp_path):
    index = tmp_path / "filings.tsv"
    index.write_text("\t".join(finances.FILINGS_COLUMNS) + "\n"
                     + "\t".join(["other-fc", "0999", "1", "T", "D", "2025-01-01", "2024-06-30",
                                  "AA", "accounts", "pdf", "", ""]) + "\n")
    pca.write_filings_index(_history(tmp_path), index)
    assert set(finances.load_filings(index)) == {"giant-fc", "other-fc"}


# ── the links ──────────────────────────────────────────────────────────────

def test_a_filing_link_is_built_from_the_company_and_the_transaction():
    assert finances.filing_url("01234567", "TXN2025") == (
        f"{SITE}/company/01234567/filing-history/TXN2025/document?format=pdf&download=0")
    assert finances.accounts_url("01234567") == (
        f"{SITE}/company/01234567/filing-history?category=accounts")


def test_a_season_takes_the_filing_made_up_in_that_year_and_an_amendment_wins():
    filings = [{"made_up_date": "2025-06-30", "filing_date": "2026-03-01", "transaction_id": "A"},
               {"made_up_date": "2025-06-30", "filing_date": "2026-05-01", "transaction_id": "AMD"},
               {"made_up_date": "2024-06-30", "filing_date": "2025-03-01", "transaction_id": "B"}]
    assert finances.filing_for_season(filings, 2025)["transaction_id"] == "AMD"
    assert finances.filing_for_season(filings, 2023) is None


def test_the_link_check_reports_what_the_register_answered(tmp_path):
    index = tmp_path / "filings.tsv"
    pca.write_filings_index(_history(tmp_path), index)
    lines = pca.check_links(index, get=lambda url: 200)
    assert len(lines) == 2 and all("HTTP 200" in l for l in lines)
    assert "TXN2025/document" in lines[0]


# ── the team page ──────────────────────────────────────────────────────────

INDEX = {"giant-fc": [
    {"club_id": "giant-fc", "company_number": "01234567", "transaction_id": "TXN2025",
     "made_up_date": "2025-06-30", "filing_date": "2026-03-27", "paper_filed": "yes"},
    {"club_id": "giant-fc", "company_number": "01234567", "transaction_id": "TXN2024",
     "made_up_date": "2024-06-30", "filing_date": "2025-03-20", "paper_filed": ""}]}


def test_each_season_links_the_accounts_filed_for_it(tmp_path, monkeypatch):
    monkeypatch.setattr(finances, "load_filings", lambda path=None: INDEX)
    out = _build_with_finances(tmp_path, monkeypatch, [
        _full_row("giant-fc", 2025), _full_row("giant-fc", 2024)])
    page = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "filing-history/TXN2025/document?format=pdf" in page
    assert "filing-history/TXN2024/document?format=pdf" in page
    assert "filing-history?category=accounts" in page
    assert "https://example.invalid" in page          # the press source is kept beside it


def test_a_row_about_another_company_is_not_linked_to_this_one_s_filing(tmp_path, monkeypatch):
    """A holding company's row is not the club company's accounts."""
    monkeypatch.setattr(finances, "load_filings", lambda path=None: INDEX)
    out = _build_with_finances(tmp_path, monkeypatch, [
        _full_row("giant-fc", 2025, company_number="09999999")])
    page = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "TXN2025" not in page


def test_club_facts_links_the_latest_accounts_and_every_filing(tmp_path, monkeypatch):
    monkeypatch.setattr(finances, "load_filings", lambda path=None: INDEX)
    builder = SiteBuilder(_db_on_disk(tmp_path), tmp_path / "site", charts_enabled=False)
    reg = {"number": "01234567", "status": "active", "company": "GIANT FC LIMITED",
           "controller": {"name": None, "where": None, "band": None, "via": []},
           "charges": {"outstanding": 0, "total": 0, "satisfied": 0, "lenders": [], "property": False},
           "insolvency": [], "warnings": []}
    rows = builder._register_rows("giant-fc", {}, {"register": {"giant-fc": reg}})
    accounts = next(r for r in rows if r["label"] == "Accounts")["value"]
    assert "TXN2025/document" in accounts
    assert "accounts to 30 June 2025" in accounts
    assert "filed 27 March 2026 on paper" in accounts
    assert "every filing" in accounts


def test_a_club_with_a_company_but_no_indexed_filing_still_links_every_filing(tmp_path, monkeypatch):
    monkeypatch.setattr(finances, "load_filings", lambda path=None: {})
    builder = SiteBuilder(_db_on_disk(tmp_path), tmp_path / "site", charts_enabled=False)
    reg = {"number": "01234567", "status": "active", "company": "GIANT FC LIMITED",
           "controller": {"name": None, "where": None, "band": None, "via": []},
           "charges": {"outstanding": 0, "total": 0, "satisfied": 0, "lenders": [], "property": False},
           "insolvency": [], "warnings": []}
    rows = builder._register_rows("giant-fc", {}, {"register": {"giant-fc": reg}})
    accounts = next(r for r in rows if r["label"] == "Accounts")["value"]
    assert "every filing" in accounts and "document?" not in accounts


def test_the_every_filing_link_appears_before_the_index_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(finances, "load_filings", lambda path=None: {})
    out = _build_with_finances(tmp_path, monkeypatch, [_full_row("giant-fc", 2025)])
    page = (out / "team" / "giant-fc" / "index.html").read_text()
    assert "company/01234567/filing-history?category=accounts" in page
