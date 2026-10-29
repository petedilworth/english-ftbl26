"""
What the PDF-only filings are, and their text.

The external tools (poppler, tesseract) are stubbed: what is under test
is the decision each filing gets - read the text layer, OCR it, or record
that the budget ran out - and that no filing is read twice.
"""
import csv
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import read_pdf_accounts as rpa                          # noqa: E402

TEXT = ("Balance sheet as at 30 June 2025\nNet current assets 12,400\n"
        "Average number of employees 14\n") * 40   # ~600 characters a page


@pytest.fixture
def tools(monkeypatch):
    calls = {"ocr": 0}
    monkeypatch.setattr(rpa.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(rpa, "pages", lambda pdf: 6)

    def layer(pdf):
        return TEXT if "electronic" in pdf.name else "  COMPANIES HOUSE  "
    monkeypatch.setattr(rpa, "text_layer", layer)

    def ocr(pdf):
        calls["ocr"] += 1
        return TEXT
    monkeypatch.setattr(rpa, "ocr", ocr)
    return calls


def _census(out):
    with (out / "census.tsv").open() as fh:
        return {r["file"]: r for r in csv.DictReader(fh, delimiter="\t")}


def test_a_pdf_with_a_text_layer_is_read_without_ocr(tmp_path, tools):
    docs, out = tmp_path / "docs", tmp_path / "out"
    docs.mkdir()
    (docs / "electronic-fc__1.pdf").write_bytes(b"%PDF")
    rpa.read_all(docs, out, budget_minutes=5)
    row = _census(out)["electronic-fc__1.pdf"]
    assert row["text_layer"] == "yes" and row["method"] == "text"
    assert row["balance_sheet"] == row["employees_note"] == "yes"
    assert tools["ocr"] == 0
    assert "method: text" in (out / "electronic-fc__1.txt").read_text()


def test_a_scan_is_ocrd(tmp_path, tools):
    docs, out = tmp_path / "docs", tmp_path / "out"
    docs.mkdir()
    (docs / "scanned-fc__1.pdf").write_bytes(b"%PDF")
    rpa.read_all(docs, out, budget_minutes=5)
    row = _census(out)["scanned-fc__1.pdf"]
    assert row["text_layer"] == "no" and row["method"] == "ocr"
    assert tools["ocr"] == 1


def test_a_filing_the_budget_did_not_reach_is_recorded_not_dropped(tmp_path, tools):
    docs, out = tmp_path / "docs", tmp_path / "out"
    docs.mkdir()
    (docs / "scanned-fc__1.pdf").write_bytes(b"%PDF")
    rpa.read_all(docs, out, budget_minutes=0)
    row = _census(out)["scanned-fc__1.pdf"]
    assert row["method"] == "not reached"
    assert not (out / "scanned-fc__1.txt").exists()


def test_a_filing_already_read_is_not_ocrd_again(tmp_path, tools):
    """OCR is the slow part; its budget goes on filings not yet read."""
    docs, out = tmp_path / "docs", tmp_path / "out"
    docs.mkdir()
    (docs / "scanned-fc__1.pdf").write_bytes(b"%PDF")
    rpa.read_all(docs, out, budget_minutes=5)
    rpa.read_all(docs, out, budget_minutes=5)
    assert tools["ocr"] == 1
    assert _census(out)["scanned-fc__1.pdf"]["method"] == "ocr"


def test_without_the_tools_every_pdf_is_still_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(rpa.shutil, "which", lambda name: None)
    docs, out = tmp_path / "docs", tmp_path / "out"
    docs.mkdir()
    (docs / "any-fc__1.pdf").write_bytes(b"%PDF")
    rpa.read_all(docs, out, budget_minutes=5)
    assert _census(out)["any-fc__1.pdf"]["method"] == "unread"
