#!/usr/bin/env python3
"""
Fetch each matched club's latest statutory accounts from Companies House,
for scripts/parse_club_accounts.py to read.

The Python, Actions-run successor to scripts/fetch_club_accounts.ps1,
which had to run on a machine that could reach the API. Same rules:

- WHICH COMPANY. The matches in data/companies_house.json that
  src/companies.py trusts: the reviewed name matches, and the automatic
  ones that rest on evidence from the register. A filing fetched against
  the wrong company is worse than none - its figures are real and belong
  to someone else.
- WHICH FILINGS. The two most recent accounts filings, enough for the
  year-on-year change the club pages show. More clubs, not more history.
- WHICH FORMAT. iXBRL (application/xhtml+xml) where the document API has
  it: the figures in it are tagged, so nobody has to decide which number
  is turnover. Otherwise the PDF is recorded as a PDF - a scanned set of
  accounts carries no tagged figures and cannot be parsed, and saying so
  is better than writing nothing.

Writes, per club, into the output directory (not committed):
    <club_id>__filings.json   the accounts filing history
    <club_id>__<n>.xhtml      the nth filing as iXBRL
    <club_id>__<n>.pdf        the nth filing where only a PDF exists

The API key comes from CH_API_KEY and is sent only to Companies House.
The documents themselves come back as a redirect to a storage host, and
requests drops the Authorization header when a redirect leaves the
original host, so the key never travels there.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import companies  # noqa: E402
from fetch_companies_house import Register  # noqa: E402

FORMATS = [("application/xhtml+xml", "xhtml"), ("application/xml", "xhtml"), ("application/pdf", "pdf")]


def matched(path: Path = companies.SOURCE) -> dict[str, dict]:
    """club_id -> {company_number, entity_name} for every trusted match."""
    data = companies.load(path) or {}
    out = {}
    for cid, entry in (data.get("clubs") or {}).items():
        co = entry.get("company") or {}
        if co.get("number") and companies.trusted(entry):
            out[cid] = {"company_number": co["number"], "entity_name": (co.get("name") or "").title()}
    return out


def document(reg: Register, metadata_url: str, stem: Path) -> str | None:
    """Save one filing in the best format offered; return the extension saved, or None."""
    meta = None
    for attempt in range(4):
        time.sleep(reg.delay)
        try:
            r = reg.s.get(metadata_url, headers={"Accept": "application/json"}, timeout=30)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        reg.calls += 1
        if r.status_code == 200:
            meta = r.json()
            break
        if r.status_code in (401, 403):
            raise SystemExit(f"Companies House refused the key (HTTP {r.status_code}).")
        if r.status_code == 404:
            return None
        time.sleep(2 ** attempt * (5 if r.status_code == 429 else 1))
    if not meta:
        return None
    offered = set((meta.get("resources") or {}).keys())
    for mime, ext in FORMATS:
        if offered and mime not in offered:
            continue
        time.sleep(reg.delay)
        try:
            r = reg.s.get(metadata_url.rstrip("/") + "/content", headers={"Accept": mime}, timeout=60)
        except requests.RequestException:
            continue
        reg.calls += 1
        if r.status_code == 200 and r.content:
            stem.with_suffix("." + ext).write_bytes(r.content)
            return ext
    return None


def run(reg: Register, out: Path, clubs: dict[str, dict], filings: int = 2) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tally = {"clubs": 0, "xhtml": 0, "pdf": 0, "none": 0, "no_filings": []}
    for i, (cid, co) in enumerate(sorted(clubs.items()), 1):
        history = reg.get(f"/company/{co['company_number']}/filing-history", category="accounts",
                          items_per_page=20) or {}
        items = [x for x in history.get("items") or [] if (x.get("links") or {}).get("document_metadata")]
        (out / f"{cid}__filings.json").write_text(json.dumps(history), encoding="utf-8")
        if not items:
            tally["no_filings"].append(cid)
        for n, item in enumerate(items[:filings], 1):
            got = document(reg, item["links"]["document_metadata"], out / f"{cid}__{n}")
            tally[got or "none"] += 1
        tally["clubs"] += 1
        if i % 20 == 0:
            print(f"{i}/{len(clubs)} clubs, {tally['xhtml']} iXBRL, {tally['pdf']} PDF", flush=True)
    return tally


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch the latest accounts filings for every matched club.")
    ap.add_argument("--out", type=Path, default=ROOT / "ch-accounts")
    ap.add_argument("--filings", type=int, default=2)
    ap.add_argument("--clubs", help="comma-separated club ids, for a trial run")
    args = ap.parse_args()
    key = os.environ.get("CH_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set the CH_API_KEY secret.")
    clubs = matched()
    if args.clubs:
        want = set(args.clubs.split(","))
        clubs = {k: v for k, v in clubs.items() if k in want}
    # The mapping the parser reads alongside the documents: one row per club, the company it filed as.
    (args.out).mkdir(parents=True, exist_ok=True)
    (args.out / "mapping.json").write_text(json.dumps(clubs, indent=1), encoding="utf-8")
    tally = run(Register(key), args.out, clubs, args.filings)
    print(f"{tally['clubs']} clubs: {tally['xhtml']} iXBRL, {tally['pdf']} PDF only, {tally['none']} unavailable; "
          f"{len(tally['no_filings'])} with no accounts filings")


if __name__ == "__main__":
    main()
