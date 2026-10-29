#!/usr/bin/env python3
"""
Get the text out of the accounts filings that exist only as PDFs.

WHY. 109 of the filings the accounts workflow fetched have no iXBRL: the
document API offers them as a PDF and nothing else, so they carry no
tagged figures and the parser skips them. Most are small clubs, and most
of those filed on paper - Companies House scans a paper filing, so the
PDF is a picture of a page with no text in it at all.

WHAT THIS DOES, AND WHAT IT LEAVES FOR LATER. It does not read figures.
It finds out what each PDF is and gets its text out, because the plan for
reading figures from them depends on both:

  - whether the PDF has a text layer (an electronic PDF does; a scan
    does not), from pdftotext;
  - where it does not, the text by OCR, from tesseract, on the first
    MAX_PAGES pages - a small company's balance sheet is on page two to
    five, and OCR is the slow part of the whole workflow;
  - whether the text holds a balance sheet and an employee note at all.

It writes, into the output directory:

    census.tsv           one row per PDF: what it is and what was found
    <club_id>__<n>.txt   the text, with a header saying how it was got

The text is committed, so the figure-reading step can be written and
tested against real filings here rather than against guesses - the same
reason the iXBRL facts are committed.

OCR has a time budget. A filing it did not reach is recorded as such
rather than silently missing, and the next run picks it up, because a
filing whose text is already on file is not read again.

    python3 scripts/read_pdf_accounts.py DIRECTORY --out data/companies/pdf
"""

import argparse
import csv
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from parse_club_accounts import document_meta             # noqa: E402

OUT = PROJECT_ROOT / "data" / "companies" / "pdf"
MAX_PAGES = 12
# A PDF with fewer characters than this per page is a scan with, at most,
# a stamped header on it.
TEXT_LAYER_CHARS = 200

logger = logging.getLogger("read_pdf_accounts")

CENSUS_COLUMNS = [
    "club_id", "file", "document", "filing_date", "made_up_date", "paper_filed",
    "pages", "text_layer", "method", "chars", "seconds",
    "balance_sheet", "employees_note", "net_assets_line",
]

# What a small company's accounts say, in the words they all use. Their
# presence says the text is good enough to read figures from; their
# absence in an OCR'd filing says the OCR was not.
BALANCE_SHEET = re.compile(r"balance\s+sheet", re.I)
EMPLOYEES = re.compile(r"average\s+number\s+of\s+(?:employees|persons|staff)", re.I)
NET_ASSETS = re.compile(r"net\s+(?:current\s+)?(?:assets|liabilities)", re.I)


def _run(args: list[str], timeout: int = 120) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def pages(pdf: Path) -> int | None:
    match = re.search(r"^Pages:\s+(\d+)", _run(["pdfinfo", str(pdf)]), re.M)
    return int(match.group(1)) if match else None


def text_layer(pdf: Path) -> str:
    return _run(["pdftotext", "-layout", "-l", str(MAX_PAGES), str(pdf), "-"])


def ocr(pdf: Path) -> str:
    """
    Render each page and OCR it. --psm 6 reads the page as one block of
    text, which keeps a balance sheet's label and its figures on one line
    far more often than the default page-layout analysis does.
    """
    with tempfile.TemporaryDirectory() as tmp:
        _run(["pdftoppm", "-r", "200", "-gray", "-l", str(MAX_PAGES), "-png",
              str(pdf), f"{tmp}/p"], timeout=300)
        parts = []
        for image in sorted(Path(tmp).glob("p*.png")):
            parts.append(_run(["tesseract", str(image), "-", "--psm", "6"], timeout=120))
            parts.append("\f")
        return "".join(parts)


def read_all(directory: Path, out: Path, budget_minutes: float) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    have_tools = all(shutil.which(t) for t in ("pdfinfo", "pdftotext"))
    have_ocr = bool(shutil.which("tesseract") and shutil.which("pdftoppm"))
    if not have_tools:
        logger.warning("poppler-utils not installed - recording the PDFs without reading them")
    if not have_ocr:
        logger.warning("tesseract not installed - scanned PDFs will not be OCR'd")

    deadline = time.monotonic() + budget_minutes * 60
    rows = []
    for pdf in sorted(directory.glob("*.pdf")):
        meta = document_meta(directory, pdf)
        target = out / f"{pdf.stem}.txt"
        row = {c: "" for c in CENSUS_COLUMNS}
        row.update(club_id=meta["club_id"], file=pdf.name, document=meta["document"],
                   filing_date=meta["filing_date"], made_up_date=meta["made_up_date"],
                   paper_filed=meta["paper_filed"])
        n = pages(pdf) if have_tools else None
        row["pages"] = n or ""

        started = time.monotonic()
        body, method = "", ""
        # Read once. A text already on file for the same document is kept,
        # so OCR's time budget is spent only on filings not yet read.
        if target.exists() and f"document: {meta['document']}\n" in target.read_text(
                encoding="utf-8", errors="replace")[:400]:
            body = target.read_text(encoding="utf-8", errors="replace")
            method = re.search(r"^method: (\S+)", body, re.M).group(1) \
                if re.search(r"^method: (\S+)", body, re.M) else "cached"
            row["text_layer"] = "yes" if method == "text" else "no"
        elif have_tools:
            layer = text_layer(pdf)
            per_page = len(layer.strip()) / max(1, min(n or 1, MAX_PAGES))
            row["text_layer"] = "yes" if per_page >= TEXT_LAYER_CHARS else "no"
            if row["text_layer"] == "yes":
                body, method = layer, "text"
            elif have_ocr and time.monotonic() < deadline:
                body, method = ocr(pdf), "ocr"
            else:
                method = "not reached" if have_ocr else "no ocr"
            if body:
                header = (f"source: Companies House filing, {pdf.name}\n"
                          f"document: {meta['document']}\n"
                          f"made_up_date: {meta['made_up_date']}\n"
                          f"method: {method}\n"
                          f"pages_read: {min(n or MAX_PAGES, MAX_PAGES)} of {n or '?'}\n\n")
                target.write_text(header + body, encoding="utf-8")
        row["method"] = method or "unread"
        row["seconds"] = f"{time.monotonic() - started:.1f}"
        row["chars"] = len(body)
        row["balance_sheet"] = "yes" if BALANCE_SHEET.search(body) else ""
        row["employees_note"] = "yes" if EMPLOYEES.search(body) else ""
        row["net_assets_line"] = "yes" if NET_ASSETS.search(body) else ""
        rows.append(row)
        logger.info("%-34s %-11s %s pages, %s chars", pdf.name, row["method"],
                    row["pages"] or "?", row["chars"])

    with (out / "census.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, CENSUS_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def summarise(rows: list[dict]) -> None:
    def count(key, value="yes"):
        return sum(1 for r in rows if r[key] == value)
    logger.info("%d PDF filings: %d with a text layer, %d scanned", len(rows),
                count("text_layer"), count("text_layer", "no"))
    logger.info("   filed on paper: %d", count("paper_filed"))
    for method in ("text", "ocr", "cached", "not reached", "no ocr", "unread"):
        if count("method", method):
            logger.info("   %-12s %d", method, count("method", method))
    logger.info("   text holds a balance sheet: %d, an employee note: %d, a net assets line: %d",
                count("balance_sheet"), count("employees_note"), count("net_assets_line"))


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--budget-minutes", type=float, default=40.0)
    args = parser.parse_args()
    summarise(read_all(Path(args.directory), Path(args.out), args.budget_minutes))


if __name__ == "__main__":
    main()
