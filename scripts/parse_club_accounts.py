#!/usr/bin/env python3
"""
Read figures out of the iXBRL accounts fetched in stage 2.

WHAT iXBRL IS, AND WHY IT IS WORTH THIS. A set of accounts filed at
Companies House is an XHTML document with the figures tagged inline:

    <ix:nonFraction name="core:TurnoverRevenue" contextRef="d2024"
                    unitRef="GBP" scale="3" sign="-">1,234</ix:nonFraction>

The tag says which concept the number is, the context says what period it
covers, and scale and sign say how to read it. So the turnover is
readable without anyone deciding which number on the page is turnover -
which is the difference between this and transcribing a PDF, and the
reason only iXBRL filings are parsed here at all.

WHAT IT DOES NOT SOLVE. Which concept name a filer used. The FRC
taxonomies have changed repeatedly and a small company's software may tag
turnover as core:TurnoverRevenue, uk-gaap:TurnoverGrossOperatingRevenue,
or not at all. So each field carries a CANDIDATE SET, and - this is the
important part - every file where none of them matched is REPORTED rather
than filled with the nearest number on the page. A parser that guesses is
worse than one that says it could not read something, because the guess
arrives as a figure on a club page with nothing to mark it as doubtful.

WHAT IT REFUSES TO DO. Overwrite anything collected by hand. The rows
already in club_finances.csv were read from filings by a person and carry
notes and judgements a parser cannot reproduce; a machine-read row fills
a club-season that is blank, and never replaces a researched one. Every
row this writes carries the flag `ixbrl_auto`, so which is which stays
answerable forever rather than for as long as anyone remembers.

    python3 scripts/parse_club_accounts.py DIRECTORY_OF_DOCUMENTS
    python3 scripts/parse_club_accounts.py DIRECTORY --apply
"""

import argparse
import csv
import json
import logging
import re
import sys
from pathlib import Path
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import finances                                          # noqa: E402

FINANCES_CSV = PROJECT_ROOT / "club_finances.csv"
MAPPING = PROJECT_ROOT / "data" / "club-companies.tsv"

logger = logging.getLogger("parse_club_accounts")

# The concept names each figure might be tagged under, most specific
# first. Local names only: the prefix varies with the taxonomy version
# and says nothing useful.
#
# These are a starting set, not a closed one. The point of reporting
# unmatched files is that this list is expected to grow when real filings
# show a spelling it does not have.
CONCEPTS = {
    "turnover": [
        "TurnoverRevenue",
        "Turnover",
        "TurnoverGrossOperatingRevenue",
        "RevenueFromContractsWithCustomers",
    ],
    "staff_costs": [
        "StaffCostsEmployeeBenefitsExpense",
        "StaffCosts",
        "WagesSalaries",
        "EmployeeBenefitsExpense",
    ],
    "profit_before_tax": [
        "ProfitLossOnOrdinaryActivitiesBeforeTax",
        "ProfitLossBeforeTax",
    ],
    "net_assets": [
        "NetAssetsLiabilities",
        "ShareholdersFunds",
        "Equity",
    ],
}

# A balance sheet exists in every filing, including the small-company
# ones that carry no profit-and-loss at all. Finding one of these and no
# turnover is what distinguishes "filed, discloses nothing" from "could
# not be read" - two very different findings.
BALANCE_SHEET_CONCEPTS = set(CONCEPTS["net_assets"]) | {
    "FixedAssets", "CurrentAssets", "TotalAssetsLessCurrentLiabilities",
    "CalledUpShareCapital",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _concept(name: str) -> str:
    """core:TurnoverRevenue -> TurnoverRevenue."""
    return (name or "").rsplit(":", 1)[-1]


def _number(element) -> int | None:
    """
    The value of one tagged fact, in whole pounds.

    Three modifiers, all of which change the answer by orders of
    magnitude or by its sign, and all of which are attributes rather than
    anything visible in the text: scale is a power of ten the displayed
    figure was divided by, sign="-" means the displayed figure is
    negative, and the text itself is formatted for humans.
    """
    text = "".join(element.itertext()).strip()
    text = re.sub(r"[,\s ]", "", text)
    if text in ("", "-", "–", "—"):
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        value = float(text)
    except ValueError:
        return None
    value *= 10 ** int(element.get("scale") or 0)
    if negative or element.get("sign") == "-":
        value = -value
    return int(round(value))


def _contexts(root) -> dict[str, dict]:
    """{context id: {"end": date, "instant": bool}} for every context."""
    out = {}
    for element in root.iter():
        if _local(element.tag) != "context":
            continue
        cid = element.get("id")
        end = instant = None
        for child in element.iter():
            name = _local(child.tag)
            if name == "endDate":
                end = (child.text or "").strip()
            elif name == "instant":
                instant = (child.text or "").strip()
        if cid:
            out[cid] = {"end": end or instant, "instant": end is None}
    return out


def facts(path: Path) -> dict:
    """
    Every tagged fact in one document, as
    {concept: [(period_end, value), ...]}, plus the concepts seen.

    Returns an empty reading rather than raising on a document that will
    not parse: a filing that is a scanned PDF renamed, or truncated by a
    failed download, is a thing to report and move past.
    """
    try:
        root = ElementTree.fromstring(path.read_bytes())
    except ElementTree.ParseError as error:
        logger.debug("%s: not parseable XML (%s)", path.name, error)
        return {"values": {}, "concepts": set(), "parsed": False}

    contexts = _contexts(root)
    values: dict[str, list[tuple[str | None, int]]] = {}
    seen = set()
    for element in root.iter():
        if _local(element.tag) not in ("nonFraction", "nonNumeric"):
            continue
        concept = _concept(element.get("name"))
        seen.add(concept)
        if _local(element.tag) != "nonFraction":
            continue
        value = _number(element)
        if value is None:
            continue
        end = (contexts.get(element.get("contextRef")) or {}).get("end")
        values.setdefault(concept, []).append((end, value))
    return {"values": values, "concepts": seen, "parsed": True}


def _pick(reading: dict, field: str) -> tuple[int | None, str | None, str | None]:
    """
    One field's value, its period end, and the concept it came from.

    Where a concept appears for several periods - accounts show the prior
    year beside the current one - the latest period wins, which is the
    year the filing is actually for.
    """
    for concept in CONCEPTS[field]:
        entries = reading["values"].get(concept)
        if not entries:
            continue
        end, value = max(entries, key=lambda e: (e[0] or ""))
        return value, end, concept
    return None, None, None


def read_document(path: Path) -> dict:
    """One document to the row it supports, or a stated reason it cannot."""
    reading = facts(path)
    if not reading["parsed"]:
        return {"ok": False, "reason": "not parseable as XML"}
    if not reading["concepts"]:
        return {"ok": False, "reason": "no iXBRL tags - probably not a tagged filing"}

    out = {"ok": True, "concepts": reading["concepts"], "fields": {}, "sources": {}}
    for field in CONCEPTS:
        value, end, concept = _pick(reading, field)
        if value is not None:
            out["fields"][field] = value
            out["sources"][field] = concept
            out.setdefault("period_end", end)
    # period_end from the profit-and-loss where there is one: a balance
    # sheet date is an instant and can sit a day either side of it.
    for field in ("turnover", "profit_before_tax", "staff_costs"):
        value, end, _ = _pick(reading, field)
        if value is not None and end:
            out["period_end"] = end
            break

    if "turnover" in out["fields"]:
        out["disclosure"] = finances.DISCLOSURE_FULL
    elif out["fields"] or reading["concepts"] & BALANCE_SHEET_CONCEPTS:
        # Something was read and it was not turnover. That is the
        # small-company or abridged regime doing exactly what it permits -
        # a balance sheet, sometimes a profit, and no revenue line.
        # Recorded as a state rather than as a gap, because a club that
        # discloses nothing is a fact about the club, and because the
        # figures that ARE here cannot be published beside it: the loader
        # refuses money on a non-full disclosure, and is right to.
        out["disclosure"] = finances.DISCLOSURE_SMALL_COMPANY
    else:
        return {"ok": False,
                "reason": "tagged, but nothing recognised in it",
                "concepts": reading["concepts"]}
    return out


def _season(period_end: str | None) -> int | None:
    """
    The season a set of accounts belongs to, by the calendar year its
    period ends in - which is what the hand-collected rows already do:
    2024-05-31 and 2024-06-30 are both 2024.
    """
    match = re.match(r"(\d{4})-(\d{2})", period_end or "")
    return int(match.group(1)) if match else None


def existing_rows() -> set[tuple[str, int]]:
    """(club_id, season) already in club_finances.csv - never overwritten."""
    if not FINANCES_CSV.exists():
        return set()
    with FINANCES_CSV.open(encoding="utf-8") as fh:
        return {(r["club_id"], int(r["season_end_year"]))
                for r in csv.DictReader(fh) if r.get("season_end_year")}


def mapping() -> dict[str, dict]:
    if not MAPPING.exists():
        return {}
    with MAPPING.open(encoding="utf-8") as fh:
        return {r["club_id"]: r for r in csv.DictReader(fh, delimiter="\t")}


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="directory of fetched documents")
    parser.add_argument("--apply", action="store_true",
                        help="append the rows to club_finances.csv")
    args = parser.parse_args()

    directory = Path(args.directory)
    companies = mapping()
    taken = existing_rows()

    rows, unread, pdf_only, duplicates = [], [], [], []
    for path in sorted(directory.glob("*.xhtml")):
        club_id = path.stem.split("__", 1)[0]
        company = companies.get(club_id, {})
        result = read_document(path)
        if not result["ok"]:
            unread.append((path.name, result["reason"],
                           sorted(result.get("concepts", ()))[:8]))
            continue

        season = _season(result.get("period_end"))
        if season is None:
            unread.append((path.name, "no period end date", []))
            continue
        if (club_id, season) in taken:
            duplicates.append(f"{club_id} {season}")
            continue
        taken.add((club_id, season))

        fields = result["fields"]
        full = result["disclosure"] == finances.DISCLOSURE_FULL
        row = {c: "" for c in finances.COLUMNS}
        row.update({
            "club_id": club_id,
            "season_end_year": season,
            "company_number": company.get("company_number", ""),
            "entity_name": company.get("entity_name", ""),
            "period_end": result.get("period_end", ""),
            "disclosure": result["disclosure"],
            # The loader refuses figures on anything but a full
            # disclosure, and it is right to: a club that published no
            # profit-and-loss cannot also have a turnover.
            "turnover": fields.get("turnover", "") if full else "",
            "staff_costs": fields.get("staff_costs", "") if full else "",
            "staff_costs_definition": (
                "excl_amortisation" if full and "staff_costs" in fields else ""),
            "profit_before_tax": fields.get("profit_before_tax", "") if full else "",
            "source_url": (
                f"https://find-and-update.company-information.service.gov.uk"
                f"/company/{company.get('company_number','')}/filing-history"),
            "flags": json.dumps(["ixbrl_auto"]),
        })
        rows.append(row)

    for path in sorted(directory.glob("*.pdf")):
        pdf_only.append(path.name)

    logger.info("%d rows read from %d documents", len(rows),
                len(list(directory.glob("*.xhtml"))))
    by_state = {}
    for row in rows:
        by_state[row["disclosure"]] = by_state.get(row["disclosure"], 0) + 1
    logger.info("   by disclosure: %s", by_state or "none")
    logger.info("   clubs: %d", len({r["club_id"] for r in rows}))
    if duplicates:
        logger.info("%d already collected by hand, left alone: %s",
                    len(duplicates), ", ".join(duplicates[:6]))
    if pdf_only:
        logger.warning("%d filings are PDF only and carry no tagged figures",
                       len(pdf_only))

    # The whole point. A file this could not read is named, with the
    # concepts it DID find, because that is what says which spelling to
    # add to CONCEPTS.
    if unread:
        logger.warning("%d documents could not be read:", len(unread))
        for name, reason, concepts in unread[:25]:
            logger.warning("    %-34s %s %s", name, reason,
                           ("- saw " + ", ".join(concepts)) if concepts else "")

    if not args.apply:
        logger.info("dry run - pass --apply to append to club_finances.csv")
        return

    if not rows:
        logger.info("nothing to write")
        return
    with FINANCES_CSV.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, finances.COLUMNS, lineterminator="\n")
        writer.writerows(rows)
    logger.info("appended %d rows to %s", len(rows), FINANCES_CSV.name)


if __name__ == "__main__":
    main()
