"""The accounts fetch, against a fake register and document API."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import fetch_club_accounts as fca  # noqa: E402
import parse_club_accounts as pca  # noqa: E402
from test_fetch_companies_house import FakeSession, Resp, reg  # noqa: E402

DOC = "https://frontend-doc-api.company-information.service.gov.uk/document/abc"


class Body(Resp):
    def __init__(self, content):
        super().__init__(200)
        self.content = content


class DocSession(FakeSession):
    """The register by path, plus the document API by full URL and Accept header."""

    def __init__(self, pages, docs):
        super().__init__(pages)
        self.docs = docs

    def get(self, url, params=None, timeout=None, headers=None):
        if url.startswith("https://frontend-doc-api"):
            accept = (headers or {}).get("Accept")
            hit = self.docs.get((url, accept))
            return hit if isinstance(hit, Resp) else Resp(404)
        return super().get(url, params, timeout)


def test_only_trusted_matches_are_fetched(tmp_path):
    snap = tmp_path / "companies_house.json"
    snap.write_text(json.dumps({"clubs": {
        "good-fc": {"match": "reviewed", "company": {"number": "00000001", "name": "GOOD FC LIMITED"}},
        "yacht-fc": {"match": "auto", "why": "registered office 1 miles from the ground",
                     "company": {"number": "00000002", "name": "A YACHT CLUB LIMITED"}}}}))
    got = fca.matched(snap)
    assert set(got) == {"good-fc"} and got["good-fc"]["company_number"] == "00000001"


def test_ixbrl_is_preferred_and_a_pdf_is_recorded_as_a_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(fca.time, "sleep", lambda s: None)
    pages = {"/company/00000001/filing-history": {"items": [
        {"links": {"document_metadata": DOC}}, {"links": {"document_metadata": DOC + "2"}}]}}
    docs = {
        (DOC, "application/json"): Resp(200, {"resources": {"application/xhtml+xml": {}, "application/pdf": {}}}),
        (DOC + "/content", "application/xhtml+xml"): Body(b"<html/>"),
        (DOC + "2", "application/json"): Resp(200, {"resources": {"application/pdf": {}}}),
        (DOC + "2/content", "application/pdf"): Body(b"%PDF"),
    }
    r = reg({})
    r.s = DocSession(pages, docs)
    tally = fca.run(r, tmp_path, {"good-fc": {"company_number": "00000001", "entity_name": "Good Fc Limited"}})
    assert (tally["xhtml"], tally["pdf"], tally["none"]) == (1, 1, 0)
    assert (tmp_path / "good-fc__1.xhtml").read_bytes() == b"<html/>"
    assert (tmp_path / "good-fc__2.pdf").exists() and (tmp_path / "good-fc__filings.json").exists()


def test_the_parser_reads_the_mapping_the_fetch_wrote(tmp_path):
    (tmp_path / "mapping.json").write_text(json.dumps({"auto-fc": {"company_number": "09", "entity_name": "Auto"}}))
    assert pca.mapping(tmp_path)["auto-fc"]["company_number"] == "09"
    assert "arsenal-fc" in pca.mapping(tmp_path / "nowhere")          # falls back to the reviewed file
