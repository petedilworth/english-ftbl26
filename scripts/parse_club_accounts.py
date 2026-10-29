#!/usr/bin/env python3
"""
Read everything the iXBRL accounts say, then the figures the site uses.

TWO STAGES, BECAUSE ONLY ONE OF THEM NEEDS THE DOCUMENTS.

    facts   documents -> data/companies/facts/<club_id>.tsv
            Every tagged fact in every filing: the concept, the period it
            covers, any dimensions on it, the unit and the value. Nothing
            is chosen here and nothing is thrown away.

    rows    data/companies/facts/ -> club_finances.csv
            The headline figures, picked out of those facts by concept name.

The split exists because the documents do not survive. They are fetched in
Actions, which can reach Companies House, and discarded when the job ends.
The first version of this parser read four concepts out of 270 filings and
kept nothing else, so every field added since would have meant fetching
all of them again. Now the facts are committed as plain text, and adding a
field - or correcting the concept a field is read from - is a re-run of
`rows`, here or anywhere, with no fetch at all.

WHAT iXBRL IS. A set of accounts filed at Companies House is an XHTML
document with the figures tagged inline:

    <ix:nonFraction name="core:TurnoverRevenue" contextRef="d2024"
                    unitRef="GBP" scale="3" sign="-">1,234</ix:nonFraction>

The tag says which concept the number is, the context says what period it
covers - and, through dimensions, which slice of it: creditors due within
one year are core:Creditors with a maturity dimension, not a concept of
their own - and scale and sign say how to read the number on the page.

WHAT IT DOES NOT SETTLE is which concept a filer used. The FRC taxonomies
have been renamed repeatedly and filing software differs, so each field
carries a candidate list, and data/companies/accounts-concepts.tsv counts
every concept seen and marks which field, if any, reads it. The unmapped
concepts that appear in the most filings are the list of spellings to add.

THE SMALL-COMPANY RULE, CORRECTED. A small or micro-entity filing may omit
the profit-and-loss account and must not omit the balance sheet or the
average number of employees. The first version recorded such a filing as
small_company and kept none of it; the loader now refuses profit-and-loss
figures on those rows and accepts the balance sheet (src/finances.py).

WHAT IT REFUSES TO DO. Overwrite anything a person collected. A hand row
is never changed except to fill a column that did not exist when it was
written - the balance sheet, the headcount - and then only from a filing
by the same entity the row names, because a holding company and the club
company under it report different money (finances.py, first paragraph).
Every machine-read row carries ixbrl_auto and is rebuilt from the facts on
each run; a topped-up hand row carries ixbrl_balance_sheet.

    python3 scripts/parse_club_accounts.py facts DIRECTORY_OF_DOCUMENTS
    python3 scripts/parse_club_accounts.py rows [--apply]
    python3 scripts/parse_club_accounts.py DIRECTORY [--apply]   # both
"""

import argparse
import csv
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import finances                                          # noqa: E402

FINANCES_CSV = PROJECT_ROOT / "club_finances.csv"
MAPPING = PROJECT_ROOT / "data" / "club-companies.tsv"
# One file per club rather than one for everything: a Premier League group
# filing tags thousands of facts, and a single file for every club would
# approach the size at which GitHub refuses a push. Per club, a month in
# which three clubs filed changes three files.
FACTS = PROJECT_ROOT / "data" / "companies" / "facts"
CENSUS = PROJECT_ROOT / "data" / "companies" / "accounts-concepts.tsv"

logger = logging.getLogger("parse_club_accounts")

FACT_COLUMNS = [
    "club_id", "company_number", "document", "filing_date", "made_up_date",
    "concept", "prefix", "kind", "period_start", "period_end", "instant",
    "dimensions", "unit", "value",
]

# Text facts are capped. Numbers are kept whole; a text fact is usually a
# name, a date or a flag, and the few that are paragraphs of accounting
# policy are not worth a megabyte a month of repository.
TEXT_CAP = 400

# ── what each field is read from ───────────────────────────────────────────
#
# (concept, members) pairs, tried in order. Local names only: the prefix
# varies with the taxonomy version and says nothing useful.
#
#   None             the fact carries no slicing dimension
#   "Member"         exactly one, with exactly this member - exactly, because
#                    "Non-currentFinancialInstruments" contains the letters of
#                    "CurrentFinancialInstruments", and a substring test read
#                    long-term debt as short-term
#   ("A", "B")       the sum of the facts with member A and member B, for a
#                    total the filing states only in its parts: bank loans
#                    due within a year plus those due after
#
# Group/company and original/revised are not slices but qualifiers, and
# are handled apart - see QUALIFIERS.
#
# Every list below was checked against data/companies/accounts-concepts.tsv
# from the first real run, which is how the current/non-current dimension
# (used three times as often as the maturity one) was found.

DURATION, INSTANT = "duration", "instant"

CURRENT = ("CurrentFinancialInstruments", "WithinOneYear")
NON_CURRENT = ("Non-currentFinancialInstruments", "AfterOneYear")


def _split_totals(concept: str) -> list:
    """A concept stated whole, or as current plus non-current, either spelling."""
    return [(concept, None),
            (concept, ("CurrentFinancialInstruments", "Non-currentFinancialInstruments")),
            (concept, ("WithinOneYear", "AfterOneYear"))]


FIELDS: dict[str, tuple[str, list]] = {
    # profit and loss
    "turnover": (DURATION, [
        ("TurnoverRevenue", None), ("Turnover", None),
        ("TurnoverGrossOperatingRevenue", None), ("Revenue", None),
        ("RevenueFromContractsWithCustomers", None)]),
    # Staff costs and nothing narrower. WagesSalaries was a candidate here
    # and it is not the same quantity: it leaves out social security and
    # pensions, which is a fifth of a wage bill.
    "staff_costs": (DURATION, [
        ("StaffCostsEmployeeBenefitsExpense", None), ("StaffCosts", None),
        ("EmployeeBenefitsExpense", None)]),
    "operating_profit": (DURATION, [
        ("OperatingProfitLoss", None), ("ProfitLossFromOperatingActivities", None)]),
    "profit_before_tax": (DURATION, [
        ("ProfitLossOnOrdinaryActivitiesBeforeTax", None), ("ProfitLossBeforeTax", None)]),
    "profit_after_tax": (DURATION, [
        ("ProfitLoss", None), ("ProfitLossForPeriod", None),
        ("ProfitLossOnOrdinaryActivitiesAfterTax", None)]),
    "player_sales_profit": (DURATION, [
        ("GainLossOnDisposalIntangibleAssets", None),
        ("GainLossOnDisposalsIntangibleAssets", None),
        ("ProfitLossOnDisposalIntangibleAssets", None)]),
    # the notes every filing carries
    "employees": (DURATION, [
        ("AverageNumberEmployeesDuringPeriod", None),
        ("AverageNumberEmployees", None)]),
    "directors_pay": (DURATION, [
        ("DirectorRemuneration", None), ("DirectorsRemuneration", None),
        ("DirectorsEmoluments", None)]),
    # The charge for the year, from the profit-and-loss where a filing has
    # one and otherwise from the fixed-asset note, which every filing has.
    "amortisation": (DURATION, [
        ("AmortisationExpenseIntangibleAssets", None),
        ("AmortisationIntangibleAssets", None),
        ("AmortisationImpairmentExpenseIntangibleAssets", None),
        ("IncreaseFromAmortisationChargeForYearIntangibleAssets", None)]),
    "depreciation": (DURATION, [
        ("DepreciationExpensePropertyPlantEquipment", None),
        ("IncreaseFromDepreciationChargeForYearPropertyPlantEquipment", None)]),
    # the balance sheet
    "fixed_assets": (INSTANT, [("FixedAssets", None)]),
    "intangible_assets": (INSTANT, [
        ("IntangibleAssets", None), ("IntangibleAssetsIncludingGoodwill", None)]),
    "tangible_assets": (INSTANT, [
        ("PropertyPlantEquipment", None), ("TangibleFixedAssets", None)]),
    "current_assets": (INSTANT, [("CurrentAssets", None)]),
    "debtors": (INSTANT, _split_totals("Debtors")),
    "cash": (INSTANT, [
        ("CashBankOnHand", None), ("CashBankInHand", None),
        ("CashCashEquivalents", None)]),
    "creditors_within_year": (INSTANT, [
        *[("Creditors", m) for m in CURRENT],
        ("CreditorsDueWithinOneYear", None),
        ("CreditorsAmountsFallingDueWithinOneYear", None)]),
    "net_current_assets": (INSTANT, [("NetCurrentAssetsLiabilities", None)]),
    "total_assets_less_current_liabilities": (INSTANT, [
        ("TotalAssetsLessCurrentLiabilities", None)]),
    "creditors_after_year": (INSTANT, [
        *[("Creditors", m) for m in NON_CURRENT],
        ("CreditorsDueAfterOneYear", None),
        ("CreditorsAmountsFallingDueAfterMoreThanOneYear", None)]),
    # What the creditors are, where the notes say. Owed to group is the
    # one that matters most for football: it is how a parent company or an
    # owner funds a club, and it does not appear anywhere else.
    "bank_loans": (INSTANT, [("TotalBorrowings", None), *_split_totals("BankBorrowingsOverdrafts")]),
    "owed_to_group": (INSTANT, _split_totals("AmountsOwedToGroupUndertakings")),
    "other_creditors": (INSTANT, _split_totals("OtherCreditors")),
    "net_assets": (INSTANT, [
        ("NetAssetsLiabilities", None), ("Equity", None),
        ("ShareholdersFunds", None)]),
    "share_capital": (INSTANT, [
        ("Equity", "ShareCapital"), ("CalledUpShareCapital", None),
        ("CalledUpShareCapitalPaid", None),
        ("Equity", "ShareCapitalOrdinaryShareClass1")]),
}

PNL_FIELDS = [f for f in FIELDS if f in finances.PNL_COLUMNS]

# Text the filing states about itself. These are often carried as an
# empty fact whose context names the answer as a dimension member - the
# accounts type is a member, not a string - so both are looked at.
ENTITY_NAME = "EntityCurrentLegalOrRegisteredName"
ACCOUNTS_TYPE = ("AccountsTypeFullOrAbbreviated", "AccountsType")
AUDIT_STATUS = ("AccountsStatusAuditedOrUnaudited",)
PERIOD_END = "EndDateForPeriodCoveredByReport"
PERIOD_START = "StartDateForPeriodCoveredByReport"

# Not a tag: read from the document's text, and named so it cannot be
# mistaken for one. See _going_concern().
GOING_CONCERN = "_GoingConcernMaterialUncertainty"


# ── stage 1: documents to facts ────────────────────────────────────────────

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _split(qname: str | None) -> tuple[str, str]:
    """core:TurnoverRevenue -> ("core", "TurnoverRevenue")."""
    qname = (qname or "").strip()
    if ":" in qname:
        prefix, name = qname.split(":", 1)
        return prefix, name
    return "", qname


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _contexts(root) -> dict[str, dict]:
    """
    {context id: {"start", "end", "instant", "dims"}}.

    dims is "Dimension=Member;..." in local names, sorted, so the same
    slice reads the same in every filing. A typed member keeps its value.
    """
    out = {}
    for element in root.iter():
        if _local(element.tag) != "context":
            continue
        cid = element.get("id")
        start = end = instant = None
        dims = []
        for child in element.iter():
            name = _local(child.tag)
            if name == "startDate":
                start = _clean(child.text)
            elif name == "endDate":
                end = _clean(child.text)
            elif name == "instant":
                instant = _clean(child.text)
            elif name == "explicitMember":
                dims.append(f"{_split(child.get('dimension'))[1]}={_split(child.text)[1]}")
            elif name == "typedMember":
                dims.append(f"{_split(child.get('dimension'))[1]}={_clean(''.join(child.itertext()))}")
        if cid:
            out[cid] = {
                "start": start or "",
                "end": end or instant or "",
                "instant": instant is not None and end is None,
                "dims": ";".join(sorted(dims)),
            }
    return out


def _units(root) -> dict[str, str]:
    """{unit id: "GBP" | "pure" | "shares" | ...}."""
    out = {}
    for element in root.iter():
        if _local(element.tag) != "unit":
            continue
        measures = [_split(_clean(m.text))[1] for m in element.iter()
                    if _local(m.tag) == "measure"]
        if element.get("id"):
            out[element.get("id")] = "/".join(measures)
    return out


def _number(element) -> int | None:
    """
    The value of one tagged figure, in whole units.

    Four things change the answer and none is visible in the rendered
    number: scale is the power of ten the figure was divided by, sign="-"
    makes it negative, a bracketed figure is negative, and the format
    attribute says how to read the text - including that a dash is a
    zero, not a blank (ixt:zerodash, ixt:fixed-zero).
    """
    nil = element.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
    if nil in ("true", "1"):
        return None
    fmt = _split(element.get("format"))[1].lower()
    text = "".join(element.itertext()).strip()
    if "zero" in fmt or (text in ("-", "–", "—") and fmt):
        return 0
    if "comma-decimal" in fmt or "numcommadecimal" in fmt:
        text = text.replace(".", "").replace(",", ".")
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


# The auditor's report says "material uncertainty related to going
# concern" under its own heading only when one exists. The same words
# appear, negated, in every clean report - "we have not identified any
# material uncertainties relating to events or conditions..." - which is
# why each match is checked for a negation just before it.
_GC_POSITIVE = re.compile(
    r"material uncertainty (?:related|relating) to going concern"
    r"|(?:indicate|indicates|that) a material uncertainty exists", re.I)
_GC_NEGATION = re.compile(r"\b(?:no|not|nothing|any|without)\b[^.]{0,60}$", re.I)


def _going_concern(text: str) -> str | None:
    """The sentence that flags a material uncertainty, or None."""
    for match in _GC_POSITIVE.finditer(text):
        before = text[max(0, match.start() - 80):match.start()]
        if _GC_NEGATION.search(before):
            continue
        # From the sentence the match is in, on for a paragraph's worth:
        # the heading alone is followed by a sentence every report shares,
        # and the part that names the note comes after it.
        start = text.rfind(".", 0, match.start()) + 1
        return _clean(text[start:start + TEXT_CAP])
    return None


def extract(path: Path) -> dict:
    """
    Every fact in one document. {"parsed", "facts", "reason"}.

    Duplicates are dropped: a filing tags the same figure in the balance
    sheet and again in a note, with the same context and value, and
    counting it twice would make every census figure wrong.
    """
    try:
        root = ElementTree.fromstring(path.read_bytes())
    except ElementTree.ParseError as error:
        return {"parsed": False, "facts": [], "reason": f"not parseable as XML ({error})"}

    contexts = _contexts(root)
    units = _units(root)
    facts, seen = [], set()
    for element in root.iter():
        tag = _local(element.tag)
        if tag not in ("nonFraction", "nonNumeric"):
            continue
        prefix, concept = _split(element.get("name"))
        ctx = contexts.get(element.get("contextRef")) or {}
        if tag == "nonFraction":
            value = _number(element)
            if value is None:
                continue
            kind, value = "num", str(value)
        else:
            kind, value = "text", _clean("".join(element.itertext()))
            if len(value) > TEXT_CAP:
                value = value[:TEXT_CAP - 1] + "…"
        fact = {
            "concept": concept, "prefix": prefix, "kind": kind,
            "period_start": ctx.get("start", "") if not ctx.get("instant") else "",
            "period_end": ctx.get("end", ""),
            "instant": "1" if ctx.get("instant") else "",
            "dimensions": ctx.get("dims", ""),
            "unit": units.get(element.get("unitRef") or "", "") if kind == "num" else "",
            "value": value,
        }
        key = tuple(fact.values())
        if key not in seen:
            seen.add(key)
            facts.append(fact)

    if not facts:
        return {"parsed": True, "facts": [], "reason": "no iXBRL tags - probably not a tagged filing"}

    gc = _going_concern(_clean(" ".join(root.itertext())))
    facts.append({
        "concept": GOING_CONCERN, "prefix": "derived", "kind": "text",
        "period_start": "", "period_end": "", "instant": "", "dimensions": "",
        "unit": "", "value": gc or "none found",
    })
    return {"parsed": True, "facts": facts, "reason": None}


def is_accounts(item: dict) -> bool:
    """
    A set of accounts, as opposed to the other filings Companies House
    lists under its "accounts" category.

    The one that mattered: AA01, a one-page notice that a company is
    changing its accounting date. Twelve clubs had one of their two
    fetched "accounts" displaced by it on the first run. The fetch and the
    numbering below both use this test, so <club>__2 means the same filing
    to both.
    """
    kind = (item.get("type") or "").upper()
    if kind == "AA01":
        return False
    return kind in ("AA", "AAMD") or (item.get("description") or "").startswith("accounts")


def _filings(directory: Path, club_id: str) -> list[dict]:
    """The filing-history items the fetch saved, in the order it numbered them."""
    path = directory / f"{club_id}__filings.json"
    if not path.exists():
        return []
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [x for x in history.get("items") or []
            if (x.get("links") or {}).get("document_metadata") and is_accounts(x)]


def document_meta(directory: Path, path: Path) -> dict:
    """
    Which filing a document is: its id at the document API, filing date,
    the date its accounts are made up to, and whether it was filed on
    paper. The fetch numbers documents in filing-history order, so
    <club>__2.xhtml is the second accounts filing that has a document.
    """
    club_id, _, n = path.stem.partition("__")
    items = _filings(directory, club_id)
    try:
        item = items[int(n) - 1]
    except (ValueError, IndexError):
        return {"club_id": club_id, "document": path.stem, "filing_date": "",
                "made_up_date": "", "paper_filed": "", "type": ""}
    meta_url = item["links"]["document_metadata"]
    return {
        "club_id": club_id,
        "document": meta_url.rstrip("/").rsplit("/", 1)[-1],
        "filing_date": item.get("date") or "",
        "made_up_date": (item.get("description_values") or {}).get("made_up_date") or "",
        "paper_filed": "yes" if item.get("paper_filed") else "",
        "type": item.get("type") or "",
        "pages": item.get("pages") or "",
    }


def read_facts(path: Path = FACTS) -> list[dict]:
    """Every fact on file, from the per-club files under `path`."""
    if not path.exists():
        return []
    out = []
    for club_file in sorted(path.glob("*.tsv")):
        with club_file.open(encoding="utf-8", newline="") as fh:
            out.extend(csv.DictReader(fh, delimiter="\t"))
    return out


def write_facts(rows: list[dict], path: Path = FACTS) -> None:
    """
    One sorted file per club, so a month with no new filings writes
    byte-identical files and git records nothing. A club with no facts
    left loses its file.
    """
    by_club: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_club[r["club_id"]].append(r)
    path.mkdir(parents=True, exist_ok=True)
    for stale in path.glob("*.tsv"):
        if stale.stem not in by_club:
            stale.unlink()
    for club_id, club_rows in by_club.items():
        club_rows.sort(key=lambda r: (r["document"], r["concept"], r["period_end"],
                                      r["dimensions"], r["value"]))
        with (path / f"{club_id}.tsv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, FACT_COLUMNS, delimiter="\t", lineterminator="\n",
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(club_rows)


def mapping(directory: Path | None = None) -> dict[str, dict]:
    """
    Club -> company. The fetch writes mapping.json beside the documents -
    every match it trusted, the automatic ones too - and that wins; the
    reviewed TSV is the fallback for documents fetched the old way.
    """
    if directory is not None and (directory / "mapping.json").exists():
        return json.loads((directory / "mapping.json").read_text(encoding="utf-8"))
    if not MAPPING.exists():
        return {}
    with MAPPING.open(encoding="utf-8") as fh:
        return {r["club_id"]: r for r in csv.DictReader(fh, delimiter="\t")}


def write_filings_index(directory: Path, path: Path = finances.FILINGS_INDEX) -> int:
    """
    Every accounts filing in the histories the fetch saved, with the
    transaction id the public register addresses it by - so a team page
    can link the accounts themselves, not just the company.

    All the accounts filings a history lists, not only the two fetched:
    the older ones are as real, and their links cost nothing. Rows for a
    club not fetched this run are kept, as the facts are.
    """
    companies = mapping(directory)
    fetched, rows = set(), []
    for history in sorted(directory.glob("*__filings.json")):
        club_id = history.name.split("__", 1)[0]
        fetched.add(club_id)
        number = (companies.get(club_id) or {}).get("company_number", "")
        for n, item in enumerate(_filings(directory, club_id), 1):
            stem = directory / f"{club_id}__{n}"
            fmt = "xhtml" if stem.with_suffix(".xhtml").exists() else \
                "pdf" if stem.with_suffix(".pdf").exists() else ""
            self_link = (item.get("links") or {}).get("self") or ""
            rows.append({
                "club_id": club_id, "company_number": number, "n": str(n),
                "transaction_id": item.get("transaction_id") or self_link.rstrip("/").rsplit("/", 1)[-1],
                "document": item["links"]["document_metadata"].rstrip("/").rsplit("/", 1)[-1],
                "filing_date": item.get("date") or "",
                "made_up_date": (item.get("description_values") or {}).get("made_up_date") or "",
                "type": item.get("type") or "",
                "description": item.get("description") or "",
                "format": fmt,
                "paper_filed": "yes" if item.get("paper_filed") else "",
                "pages": str(item.get("pages") or ""),
            })
    if path.exists():
        with path.open(encoding="utf-8", newline="") as fh:
            rows += [r for r in csv.DictReader(fh, delimiter="\t") if r["club_id"] not in fetched]
    rows.sort(key=lambda r: (r["club_id"], int(r["n"] or 0)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, finances.FILINGS_COLUMNS, delimiter="\t",
                                lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def check_links(path: Path = finances.FILINGS_INDEX, get=None) -> list[str]:
    """
    Open one filing's document link and one company's accounts list on
    the public register, and say what came back.

    Run in Actions, which can reach Companies House; this repository's
    own environment cannot, so the address format the team pages use is
    confirmed where it can be, every month, rather than assumed.
    """
    filings = finances.load_filings(path)
    sample = next((rows[0] for rows in filings.values() if rows), None)
    if sample is None:
        return ["link check: no filings indexed"]
    if get is None:
        import requests

        def get(url):
            return requests.get(url, timeout=30, allow_redirects=True, stream=True,
                                headers={"User-Agent": "english-ftbl26 link check"}).status_code
    out = []
    for label, url in (("filing document", finances.filing_url(sample["company_number"],
                                                                sample["transaction_id"])),
                       ("accounts list", finances.accounts_url(sample["company_number"]))):
        try:
            status = get(url)
        except Exception as error:                           # noqa: BLE001
            status = f"failed ({error.__class__.__name__})"
        out.append(f"link check: {label} HTTP {status} - {url}")
    return out


def cmd_facts(directory: Path, facts_path: Path = FACTS,
              filings_path: Path = finances.FILINGS_INDEX) -> dict:
    """
    Read every document in `directory` into the facts file.

    Facts from documents NOT fetched this time are kept: the fetch takes
    the two latest filings, so each new year's accounts push the oldest
    out of the window, and the facts already read from it are still
    true. They are dropped only when the club is now matched to a
    different company, because then they are another company's figures.
    """
    companies = mapping(directory)
    fresh, unread, documents = [], [], []
    for path in sorted(directory.glob("*.xhtml")):
        meta = document_meta(directory, path)
        result = extract(path)
        if not result["facts"]:
            unread.append((path.name, result["reason"]))
            continue
        company = (companies.get(meta["club_id"]) or {}).get("company_number", "")
        documents.append(meta["document"])
        for fact in result["facts"]:
            fresh.append({**fact, "club_id": meta["club_id"], "company_number": company,
                          "document": meta["document"], "filing_date": meta["filing_date"],
                          "made_up_date": meta["made_up_date"]})

    done = set(documents)
    kept = []
    for row in read_facts(facts_path):
        if row["document"] in done:
            continue
        current = (companies.get(row["club_id"]) or {}).get("company_number")
        if companies and current and row["company_number"] and current != row["company_number"]:
            continue
        kept.append(row)
    write_facts(kept + fresh, facts_path)
    filings = write_filings_index(directory, filings_path)
    logger.info("filings index: %d accounts filings -> %s", filings, filings_path.name)
    logger.info("facts: %d from %d documents read now, %d kept from earlier runs -> %s/",
                len(fresh), len(done), len(kept), facts_path.name)
    return {"fresh": len(fresh), "kept": len(kept), "documents": len(done), "unread": unread}


# ── stage 2: facts to rows ─────────────────────────────────────────────────

# Dimensions that qualify a figure rather than slice it, and which value
# of each is wanted. A group filing tags the parent company's figures with
# no dimension and the consolidated group's with Consolidated - Millwall's
# net assets read as the holding company's alone until this - and the site
# reports clubs at group level wherever a group files. A filing that
# restates a year tags the figures Original and Revised, and the revision
# is the one that stands; Sheffield Wednesday's 2023 accounts tag every
# figure Original, and read as empty while this was ignored.
QUALIFIERS = {
    "GroupCompanyDataDimension": ["Consolidated", None],
    "OriginalRevisedDataDimension": ["Revised", None, "Original"],
}


def _dims(fact: dict) -> tuple[dict, dict]:
    """(slicing dims, qualifier dims) as {dimension: member}."""
    slices, quals = {}, {}
    for part in fact["dimensions"].split(";") if fact["dimensions"] else []:
        dim, _, member = part.partition("=")
        (quals if dim in QUALIFIERS else slices)[dim] = member
    return slices, quals


def _rank(quals: dict) -> tuple:
    """Lower is preferred. Unknown qualifier values sort last."""
    out = []
    for dim, order in QUALIFIERS.items():
        value = quals.get(dim)
        out.append(order.index(value) if value in order else len(order))
    return tuple(out)


def _matches(fact: dict, concept: str, member: str | None) -> bool:
    if fact["concept"] != concept or fact["kind"] != "num":
        return False
    slices, _ = _dims(fact)
    if member is None:
        return not slices
    return len(slices) == 1 and next(iter(slices.values())) == member


def _target(facts: list[dict], made_up: str) -> str:
    """
    The date the accounts are made up to. The filing history states it,
    and that is used where present; otherwise the filing's own tagged end
    date; otherwise the latest period end any fact carries.
    """
    if made_up:
        return made_up
    for f in facts:
        if f["concept"] == PERIOD_END and re.match(r"\d{4}-\d{2}-\d{2}", f["value"]):
            return f["value"][:10]
    ends = [f["period_end"] for f in facts if f["period_end"]]
    return max(ends) if ends else ""


def _on(fact: dict, kind: str, target: str) -> bool:
    if kind == INSTANT and fact["instant"] != "1":
        return False
    if kind == DURATION and fact["instant"] == "1":
        return False
    return fact["period_end"] == target


def _best(hits: list[dict], level: str = "group") -> list[dict]:
    """
    The hits carrying the most preferred qualifiers, in document order.

    level "company" keeps only the parent company's own figures and drops
    the consolidated ones entirely - not merely ranks them lower - because
    a row recorded at company level must never be filled from the group.
    """
    if level == "company":
        hits = [f for f in hits if "GroupCompanyDataDimension" not in _dims(f)[1]]
    if not hits:
        return []
    ranks = [_rank(_dims(f)[1]) for f in hits]
    top = min(ranks)
    return [f for f, r in zip(hits, ranks) if r == top]


def _pick(facts: list[dict], field: str, target: str,
          level: str = "group") -> tuple[int | None, str | None, bool, bool]:
    """
    (value, source, ambiguous, consolidated) for one field.

    Where a concept still carries different values for the same period
    after the qualifiers are resolved, the first in document order is
    taken - the primary statement - and the row is flagged, so the choice
    is visible rather than silent.
    """
    kind, candidates = FIELDS[field]
    for concept, members in candidates:
        if isinstance(members, tuple):
            parts, total, consolidated = [], 0, False
            for member in members:
                hits = _best([f for f in facts
                              if _matches(f, concept, member) and _on(f, kind, target)], level)
                if hits:
                    parts.append(member)
                    total += int(hits[0]["value"])
                    consolidated |= _dims(hits[0])[1].get("GroupCompanyDataDimension") == "Consolidated"
            if parts:
                return total, f"{concept}[{'+'.join(parts)}]", False, consolidated
            continue
        hits = _best([f for f in facts if _matches(f, concept, members) and _on(f, kind, target)],
                     level)
        if not hits:
            continue
        values = list(dict.fromkeys(int(f["value"]) for f in hits))
        source = concept + (f"[{members}]" if members else "")
        consolidated = _dims(hits[0])[1].get("GroupCompanyDataDimension") == "Consolidated"
        return values[0], source, len(values) > 1, consolidated
    return None, None, False, False


def _text_fact(facts: list[dict], names: tuple[str, ...]) -> str:
    for f in facts:
        if f["concept"] in names:
            if f["value"]:
                return f["value"]
            if f["dimensions"]:
                return f["dimensions"].split(";")[0].split("=", 1)[-1]
    return ""


def _close(a: int, b: int) -> bool:
    """Equal, allowing for a filer's own rounding of a few pounds."""
    return abs(a - b) <= max(10, abs(max(abs(a), abs(b))) // 1000)


def reconcile(fields: dict) -> tuple[list[str], list[str]]:
    """
    Check the balance sheet adds up, and correct the one error the check
    can decide: a negative figure tagged without its minus sign.

    The first real run found 9 of 202 filings whose net current assets did
    not equal current assets less short-term creditors, and most were a
    sign: Folkestone Invicta's £34,334 of current assets against £123,865
    of creditors can only give net current LIABILITIES of £89,531, and the
    filing tags it positive. Filing software that prints the brackets
    outside the tag and omits sign="-" produces exactly this.

    Where flipping the sign makes the identity hold, the identity has
    decided it, and the figure is corrected and the correction named.
    Where nothing makes it hold, the figures are left as filed and the
    failure is named - a balance sheet that does not add up is a reason to
    doubt every figure on it.

    Returns (corrected fields, identities that fail).
    """
    corrected, failed = [], []
    ca, cl, nca = (fields.get(k) for k in ("current_assets", "creditors_within_year",
                                            "net_current_assets"))
    if None not in (ca, cl, nca):
        if _close(ca - cl, nca):
            pass
        elif _close(ca - cl, -nca):
            fields["net_current_assets"] = nca = -nca
            corrected.append("net_current_assets")
        else:
            failed.append("net_current_assets")
    fa, talcl = fields.get("fixed_assets"), fields.get("total_assets_less_current_liabilities")
    if None not in (fa, nca, talcl):
        if _close(fa + nca, talcl):
            pass
        elif _close(fa + nca, -talcl):
            fields["total_assets_less_current_liabilities"] = -talcl
            corrected.append("total_assets_less_current_liabilities")
        else:
            failed.append("total_assets_less_current_liabilities")
    return corrected, failed


def derive(facts: list[dict], made_up: str = "", level: str = "group") -> dict:
    """
    One document's facts to the row they support, or a stated reason they
    do not. level is "group" - consolidated figures wherever the filing
    has them, which is how the site reports a club that files as a group -
    or "company", the reporting entity's own figures only.
    """
    if not facts:
        return {"ok": False, "reason": "no facts"}
    target = _target(facts, made_up)
    out = {"ok": True, "fields": {}, "sources": {}, "ambiguous": [],
           "period_end": target,
           "has_group": any("GroupCompanyDataDimension=" in f["dimensions"] for f in facts),
           "concepts": {f["concept"] for f in facts}}
    consolidated = False
    for field in FIELDS:
        value, source, ambiguous, group = _pick(facts, field, target, level)
        if value is None:
            continue
        out["fields"][field] = value
        out["sources"][field] = source
        consolidated |= group
        if ambiguous:
            out["ambiguous"].append(field)
    out["consolidation_level"] = "group" if consolidated else ""
    out["corrected"], out["unbalanced"] = reconcile(out["fields"])

    start = _text_fact(facts, (PERIOD_START,))[:10]
    if not re.match(r"\d{4}-\d{2}-\d{2}$", start):
        starts = [f["period_start"] for f in facts
                  if f["period_start"] and f["period_end"] == target]
        start = min(starts) if starts else ""
    out["period_start"] = start
    out["entity_name"] = _text_fact(facts, (ENTITY_NAME,))
    out["accounts_type"] = _text_fact(facts, ACCOUNTS_TYPE)
    out["audited"] = _text_fact(facts, AUDIT_STATUS)
    gc = next((f["value"] for f in facts if f["concept"] == GOING_CONCERN), "")
    out["going_concern"] = "" if gc in ("", "none found") else gc

    if "turnover" in out["fields"]:
        out["disclosure"] = finances.DISCLOSURE_FULL
    elif out["fields"]:
        # A balance sheet, a headcount, perhaps a profit, and no revenue
        # line: the small-company regime doing what it permits.
        out["disclosure"] = finances.DISCLOSURE_SMALL_COMPANY
    else:
        return {"ok": False, "reason": "tagged, but nothing recognised in it",
                "concepts": out["concepts"]}
    return out


def read_document(path: Path) -> dict:
    """One document straight to its row - extract and derive in one step."""
    result = extract(path)
    if not result["facts"]:
        return {"ok": False, "reason": result["reason"]}
    return derive(result["facts"])


def _season(period_end: str | None) -> int | None:
    """
    The season a set of accounts belongs to, by the calendar year its
    period ends in - which is what the hand-collected rows already do:
    2024-05-31 and 2024-06-30 are both 2024.
    """
    match = re.match(r"(\d{4})-(\d{2})", period_end or "")
    return int(match.group(1)) if match else None


def _months(start: str, end: str) -> str:
    m1, m2 = re.match(r"(\d{4})-(\d{2})", start or ""), re.match(r"(\d{4})-(\d{2})", end or "")
    if not (m1 and m2):
        return ""
    months = (int(m2.group(1)) - int(m1.group(1))) * 12 + int(m2.group(2)) - int(m1.group(2)) + 1
    return str(months) if 1 <= months <= 24 else ""


def _norm_entity(name: str) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().replace("&", " and "))
    text = re.sub(r"\b(the|limited|ltd|plc|public limited company|company|co)\b", " ", text)
    return " ".join(text.split())


def _flags(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def load_csv(path: Path = FINANCES_CSV) -> list[dict]:
    """Every row, with every column the loader now knows, blank where absent."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return [{c: (r.get(c) or "") for c in finances.COLUMNS} for r in csv.DictReader(fh)]


def existing_rows(path: Path = FINANCES_CSV) -> set[tuple[str, int]]:
    """(club_id, season) already in club_finances.csv."""
    return {(r["club_id"], int(r["season_end_year"]))
            for r in load_csv(path) if r.get("season_end_year")}


# Columns a hand row may be topped up with: the ones added after every
# hand row was written. Nothing a person had the chance to fill.
NEW_COLUMNS = list(dict.fromkeys(
    ["operating_profit", "profit_after_tax", "amortisation", "player_sales_profit"]
    + finances.BALANCE_COLUMNS + finances.STATUS_COLUMNS))


def build_rows(facts: list[dict], existing: list[dict]) -> dict:
    """
    Facts plus the current CSV to the new CSV, and what changed.

    Machine-read rows are rebuilt from the facts on every run, which is
    what lets a field added to FIELDS reach the rows already written. A
    hand row keeps every value it has; it gains only NEW_COLUMNS, only
    where blank, and only from a filing by the entity it names.
    """
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for f in facts:
        by_doc[f["document"]].append(f)

    derived: dict[tuple[str, int], dict] = {}
    unread = []
    for doc, doc_facts in by_doc.items():
        first = doc_facts[0]
        result = derive(doc_facts, first["made_up_date"])
        if not result["ok"]:
            unread.append((first["club_id"], doc, result["reason"],
                           sorted(result.get("concepts", ()))[:8]))
            continue
        season = _season(result["period_end"])
        if season is None:
            unread.append((first["club_id"], doc, "no period end date", []))
            continue
        result.update(club_id=first["club_id"], company_number=first["company_number"],
                      filing_date=first["filing_date"], document=doc, facts=doc_facts)
        key = (first["club_id"], season)
        # Two filings for one year is an amendment: the later one stands.
        if key not in derived or result["filing_date"] > derived[key]["filing_date"]:
            derived[key] = result

    companies = mapping()
    rows, index = [dict(r) for r in existing], {}
    for i, r in enumerate(rows):
        if r["season_end_year"]:
            index[(r["club_id"], int(r["season_end_year"]))] = i

    stats = Counter()
    mismatched = []
    for key, d in sorted(derived.items()):
        club_id, season = key
        fields = d["fields"]
        full = d["disclosure"] == finances.DISCLOSURE_FULL
        values = {f: ("" if (f in PNL_FIELDS and not full) else str(v))
                  for f, v in fields.items()}
        values.update(accounts_type=d["accounts_type"], audited=d["audited"],
                      going_concern=d["going_concern"])

        at = index.get(key)
        if at is not None and "ixbrl_auto" not in _flags(rows[at]["flags"]):
            hand = rows[at]
            same = (hand["company_number"] and hand["company_number"] == d["company_number"]) \
                or (_norm_entity(hand["entity_name"]) and d["entity_name"]
                    and _norm_entity(hand["entity_name"]) == _norm_entity(d["entity_name"]))
            if not same:
                mismatched.append(f"{club_id} {season}: row names {hand['entity_name'] or '?'}, "
                                  f"filing is {d['entity_name'] or '?'}")
                continue
            # The same entity files both its own figures and, as a group,
            # its subsidiaries' with them, and the two differ by a stadium
            # company: Reading's tangible assets are £131,898 for the
            # company and £39.8m for the group. The row says which level a
            # person meant; where it does not and the filing has both, the
            # level cannot be known and nothing is added.
            flags = _flags(hand["flags"])
            ours = next((f[len("ixbrl_fill:"):].split(",") for f in flags
                         if f.startswith("ixbrl_fill:")), None)
            if ours is None:
                ours = NEW_COLUMNS if "ixbrl_balance_sheet" in flags else []

            level = {"club": "company", "group": "group"}.get(hand["consolidation_level"])
            if level is None:
                if d["has_group"]:
                    mismatched.append(f"{club_id} {season}: group filing, and the row does not "
                                      f"say whether it records the group or the company")
                    # Withdraw anything an earlier run guessed here: those
                    # values were the parser's, and are no more knowable now.
                    for c in ours:
                        if c in hand:
                            hand[c] = ""
                    hand["flags"] = json.dumps(
                        [f for f in flags if f != "ixbrl_balance_sheet"
                         and not f.startswith("ixbrl_fill:")])
                    continue
                level = "company"
            reading = derive(d["facts"], d["period_end"], level)
            if not reading["ok"]:
                continue
            values = {f: str(v) for f, v in reading["fields"].items()}
            values.update(accounts_type=d["accounts_type"], audited=d["audited"],
                          going_concern=d["going_concern"])

            # Provenance (read above). The columns this parser wrote are
            # named in the row's flags, so a corrected reading reaches them
            # next run, while a value a person enters later is never
            # touched. A row topped up before the list existed was topped
            # up only in columns that did not exist until then: all of them
            # are ours.
            written = []
            for c in NEW_COLUMNS:
                if c in ours or not hand[c]:
                    new = values.get(c, "")
                    if new and hand[c] != new:
                        stats[f"topped:{c}"] += 1
                    if c in ours and not new:
                        hand[c] = ""
                    if new:
                        hand[c] = new
                        written.append(c)
            flags = [f for f in flags if f not in ("ixbrl_balance_sheet", "sign_corrected",
                                                    "does_not_balance")
                     and not f.startswith("ixbrl_fill:")]
            if written:
                flags += ["ixbrl_balance_sheet", "ixbrl_fill:" + ",".join(written)]
                flags += (["sign_corrected"] if reading["corrected"] else []) \
                    + (["does_not_balance"] if reading["unbalanced"] else [])
                stats["hand rows topped up"] += 1
            hand["flags"] = json.dumps(flags)
            continue

        company = companies.get(club_id) or {}
        row = {c: "" for c in finances.COLUMNS}
        row.update(values)
        row.update({
            "club_id": club_id,
            "season_end_year": str(season),
            "company_number": d["company_number"] or company.get("company_number", ""),
            "entity_name": (d["entity_name"] or company.get("entity_name", "")).strip(),
            "period_start": d["period_start"],
            "period_end": d["period_end"],
            "period_months": _months(d["period_start"], d["period_end"]),
            "consolidation_level": d["consolidation_level"],
            "disclosure": d["disclosure"],
            "staff_costs_definition": ("excl_amortisation" if full and "staff_costs" in fields
                                       else ""),
            "source_url": ("https://find-and-update.company-information.service.gov.uk"
                           f"/company/{d['company_number']}/filing-history"),
            "filing_date": d["filing_date"],
            "flags": json.dumps(["ixbrl_auto"]
                                + (["ixbrl_ambiguous"] if d["ambiguous"] else [])
                                + (["sign_corrected"] if d["corrected"] else [])
                                + (["does_not_balance"] if d["unbalanced"] else [])),
        })
        if at is not None:
            rows[at] = row
            stats["machine rows rebuilt"] += 1
        else:
            index[key] = len(rows)
            rows.append(row)
            stats["machine rows added"] += 1
        stats[d["disclosure"]] += 1

    # What the parser itself put there. A hand row's own turnover is not
    # counted: the report is about what the filings added.
    filled, topped = Counter(), Counter()
    for r in rows:
        flags = _flags(r["flags"])
        if "ixbrl_auto" in flags:
            for c in finances.MONEY_COLUMNS + finances.STATUS_COLUMNS:
                if r[c]:
                    filled[c] += 1
    for c, n in stats.items():
        if c.startswith("topped:"):
            topped[c[7:]] = n
    return {"rows": rows, "stats": stats, "unread": unread, "mismatched": mismatched,
            "filled": filled, "topped": topped, "derived": derived}


def census(facts: list[dict]) -> list[dict]:
    """
    Every concept seen, how many filings carry it, and which field reads
    it. The unmapped concepts in the most filings are what to add next.
    """
    reads = {}
    for field, (_kind, candidates) in FIELDS.items():
        for concept, member in candidates:
            tag = "+".join(member) if isinstance(member, tuple) else member
            reads.setdefault(concept, []).append(field + (f"[{tag}]" if tag else ""))
    docs, count, dimmed, example = defaultdict(set), Counter(), Counter(), {}
    for f in facts:
        c = f["concept"]
        docs[c].add(f["document"])
        count[c] += 1
        if f["dimensions"]:
            dimmed[c] += 1
        example.setdefault(c, f)
    out = []
    for c in sorted(docs, key=lambda c: (-len(docs[c]), c)):
        e = example[c]
        out.append({"concept": c, "prefix": e["prefix"], "kind": e["kind"],
                    "documents": len(docs[c]), "facts": count[c],
                    "with_dimensions": dimmed[c],
                    "read_as": ",".join(reads.get(c, [])),
                    "example": f"{e['club_id']}: {e['value'][:60]}"
                               + (f" [{e['dimensions'][:60]}]" if e["dimensions"] else "")})
    return out


def write_census(rows: list[dict], path: Path = CENSUS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, ["concept", "prefix", "kind", "documents", "facts",
                                     "with_dimensions", "read_as", "example"],
                                delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def cmd_rows(facts_path: Path = FACTS, apply: bool = False,
             csv_path: Path = FINANCES_CSV) -> dict:
    facts = read_facts(facts_path)
    result = build_rows(facts, load_csv(csv_path))
    write_census(census(facts))

    stats = result["stats"]
    logger.info("rows: %d club-seasons read from %d documents",
                len(result["derived"]), len({f["document"] for f in facts}))
    for key in ("full", "small_company", "machine rows added", "machine rows rebuilt",
                "hand rows topped up"):
        logger.info("   %-22s %d", key, stats.get(key, 0))
    logger.info("   %-38s %8s %8s", "field", "machine", "hand+")
    for c in finances.MONEY_COLUMNS + finances.STATUS_COLUMNS:
        a, b = result["filled"].get(c, 0), result["topped"].get(c, 0)
        if a or b:
            logger.info("   %-38s %8d %8d", c, a, b)
    corrected = sum(1 for r in result["rows"] if "sign_corrected" in _flags(r["flags"]))
    unbalanced = sum(1 for r in result["rows"] if "does_not_balance" in _flags(r["flags"]))
    logger.info("balance sheet check: %d rows had a missing minus sign corrected, "
                "%d do not add up and are flagged", corrected, unbalanced)
    if result["mismatched"]:
        logger.info("%d hand rows left alone - the filing is a different entity:",
                    len(result["mismatched"]))
        for line in result["mismatched"][:20]:
            logger.info("    %s", line)
    if result["unread"]:
        logger.warning("%d documents gave no row:", len(result["unread"]))
        for club, doc, reason, concepts in result["unread"][:25]:
            logger.warning("    %-28s %s%s", club, reason,
                           (" - saw " + ", ".join(concepts)) if concepts else "")

    unmapped = [c for c in census(facts) if not c["read_as"] and c["kind"] == "num"]
    if unmapped:
        logger.info("most common numeric concepts no field reads (see %s):", CENSUS.name)
        for c in unmapped[:25]:
            logger.info("    %4d filings  %s", c["documents"], c["concept"])

    if apply:
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, finances.COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(result["rows"])
        logger.info("wrote %d rows to %s", len(result["rows"]), csv_path.name)
    else:
        logger.info("dry run - pass --apply to write %s", csv_path.name)
    return result


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    argv = sys.argv[1:]
    if argv and argv[0] not in ("facts", "rows", "check-links", "-h", "--help"):
        argv = ["both"] + argv            # the original invocation: a directory
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("facts", help="documents -> data/companies/facts/")
    p.add_argument("directory")
    p.add_argument("--facts", default=str(FACTS))
    p = sub.add_parser("rows", help="data/companies/facts/ -> club_finances.csv")
    p.add_argument("--facts", default=str(FACTS))
    p.add_argument("--apply", action="store_true")
    sub.add_parser("check-links", help="open one filing link on the public register")
    p = sub.add_parser("both", help=argparse.SUPPRESS)
    p.add_argument("directory")
    p.add_argument("--facts", default=str(FACTS))
    p.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "check-links":
        for line in check_links():
            logger.info(line)
        return
    if args.command in ("facts", "both"):
        directory = Path(args.directory)
        result = cmd_facts(directory, Path(args.facts))
        pdfs = sorted(directory.glob("*.pdf"))
        if pdfs:
            logger.warning("%d filings are PDF only and carry no tagged figures", len(pdfs))
        for name, reason in result["unread"][:25]:
            logger.warning("    %-34s %s", name, reason)
    if args.command in ("rows", "both"):
        cmd_rows(Path(args.facts), apply=getattr(args, "apply", False))


if __name__ == "__main__":
    main()
