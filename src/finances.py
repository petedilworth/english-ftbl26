"""
Club financial data: the club_finances table and its CSV loader.

Figures come from statutory accounts filed at Companies House, which is
Crown copyright published under the Open Government Licence v3.0 and so
can be republished with attribution. Nothing here is an estimate: where a
club has not disclosed, that is recorded as a state (see DISCLOSURE)
rather than left as a silent null, because a club declining to publish its
turnover is itself a finding about football's finances.

Two things about this data corrupt it silently if not recorded alongside
every figure, so both are columns rather than assumptions:

- "Wages" is ambiguous by 20-40%, not by rounding. The staff-costs note in
  a set of accounts covers every employee and excludes amortisation of
  transfer fees; some published sources include amortisation; a summed
  squad wage bill is a third quantity again. staff_costs_definition says
  which one a row holds.
- Which legal entity filed changes the answer. A holding company
  consolidating a stadium, hotel or media arm reports different revenue
  from the football club company, and insolvency starts a new company
  number altogether, breaking a series mid-window. company_number and
  consolidation_level pin down what was actually read.
"""

import csv
import json
import logging
import sqlite3
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Whether the accounts disclose the figures at all. Anything other than
# "full" means the money columns are legitimately empty, and the club
# should be shown as having not disclosed rather than as missing.
DISCLOSURE_FULL = "full"
DISCLOSURE_SMALL_COMPANY = "small_company"   # filed under the small-company regime, no P&L
DISCLOSURE_NOT_FILED = "not_filed"           # overdue or not yet filed
DISCLOSURE_DISSOLVED = "dissolved"           # entity gone (liquidation, phoenix club)

DISCLOSURE_VALUES = {
    DISCLOSURE_FULL,
    DISCLOSURE_SMALL_COMPANY,
    DISCLOSURE_NOT_FILED,
    DISCLOSURE_DISSOLVED,
}

# Recorded per row because sources disagree by more than rounding.
STAFF_COSTS_DEFINITIONS = {"excl_amortisation", "incl_amortisation"}

CONSOLIDATION_LEVELS = {"club", "group"}

# The profit-and-loss account. A small-company or micro-entity filing is
# legally allowed to omit it, so these are refused on any row whose
# disclosure is not full: a club that published no profit-and-loss cannot
# also have a turnover, and one of the two would be wrong.
PNL_COLUMNS = [
    "turnover",
    "staff_costs",
    "revenue_matchday",
    "revenue_broadcast",
    "revenue_commercial",
    "operating_profit",
    "profit_before_tax",
    "profit_after_tax",
    "player_sales_profit",
    "net_debt",
]

# The balance sheet and the notes every filing must carry, the
# small-company and micro-entity regimes included. These are ALLOWED on a
# small_company row, and that is the point of separating them: refusing
# every figure on a row that withheld its profit-and-loss threw away the
# balance sheet of 192 non-league filings the law required them to file.
#
# Depreciation and amortisation are here, not with the profit-and-loss,
# because a small company states them in its fixed-asset notes, which it
# must file. net_debt stays with the profit-and-loss columns because it is
# a figure the press derives for the biggest clubs, not one a filing states.
BALANCE_COLUMNS = [
    "employees",
    "fixed_assets",
    "intangible_assets",
    "tangible_assets",
    "current_assets",
    "cash",
    "creditors_within_year",
    "net_current_assets",
    "total_assets_less_current_liabilities",
    "creditors_after_year",
    "net_assets",
    "share_capital",
    "directors_pay",
    "amortisation",
    "debtors",
    "bank_loans",
    "owed_to_group",
    "other_creditors",
    "depreciation",
]

# Whole numbers: pounds, or for employees a headcount.
MONEY_COLUMNS = PNL_COLUMNS + BALANCE_COLUMNS

# What the filing says about itself, as text.
STATUS_COLUMNS = ["accounts_type", "audited", "going_concern"]

REQUIRED_COLUMNS = {"club_id", "season_end_year", "disclosure"}

# Column order used for the INSERT; also the canonical CSV column order.
# New columns go at the END, so a CSV written before they existed still
# reads, and the hand-collected rows keep their shape.
COLUMNS = [
    "club_id", "season_end_year", "company_number", "entity_name",
    "consolidation_level", "period_start", "period_end", "period_months",
    "disclosure", "turnover", "staff_costs", "staff_costs_definition",
    "revenue_matchday", "revenue_broadcast", "revenue_commercial",
    "profit_before_tax", "net_debt", "source_url", "filing_date", "flags",
    "operating_profit", "profit_after_tax", "amortisation", "player_sales_profit",
    "employees", "fixed_assets", "intangible_assets", "tangible_assets",
    "current_assets", "cash", "creditors_within_year", "net_current_assets",
    "total_assets_less_current_liabilities", "creditors_after_year", "net_assets",
    "share_capital", "directors_pay",
    "accounts_type", "audited", "going_concern",
    "debtors", "bank_loans", "owed_to_group", "other_creditors", "depreciation",
]
assert set(COLUMNS) >= set(PNL_COLUMNS) | set(BALANCE_COLUMNS) | set(STATUS_COLUMNS)
assert len(COLUMNS) == len(set(COLUMNS))

_INT_COLUMNS = set(MONEY_COLUMNS) | {"season_end_year", "period_months"}
_NOT_NULL = {"club_id", "season_end_year", "disclosure"}

CREATE_CLUB_FINANCES_SQL = (
    "CREATE TABLE IF NOT EXISTS club_finances (\n"
    + ",\n".join(
        f"    {c} {'INT' if c in _INT_COLUMNS else 'TEXT'}"
        + (" NOT NULL" if c in _NOT_NULL else "")
        for c in COLUMNS)
    + ",\n    PRIMARY KEY (club_id, season_end_year)\n);"
)


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Add any column a database built before it existed is missing.

    england.db is committed and refreshed daily, so its club_finances was
    created long before the balance-sheet columns, and CREATE TABLE IF NOT
    EXISTS leaves an old table exactly as it was.
    """
    have = {r[1] for r in conn.execute("PRAGMA table_info(club_finances)")}
    for col in COLUMNS:
        if col not in have:
            kind = "INT" if col in _INT_COLUMNS else "TEXT"
            conn.execute(f"ALTER TABLE club_finances ADD COLUMN {col} {kind}")


# ── links to the filed accounts themselves ─────────────────────────────────
#
# data/companies/filings.tsv is written by scripts/parse_club_accounts.py
# from the filing history the accounts workflow fetches: one row per
# accounts filing, with the transaction id Companies House's public site
# addresses it by. The links are built from that id and the company
# number, and the accounts workflow checks one of each live
# (parse_club_accounts.py check-links), because this repository's own
# environment cannot reach the site to confirm the address.

FILINGS_INDEX = Path(__file__).resolve().parent.parent / "data" / "companies" / "filings.tsv"
FILINGS_COLUMNS = [
    "club_id", "company_number", "n", "transaction_id", "document", "filing_date",
    "made_up_date", "type", "description", "format", "paper_filed", "pages",
]
CH_SITE = "https://find-and-update.company-information.service.gov.uk"


def accounts_url(company_number: str) -> str:
    """Every accounts filing the company has made, on the public register."""
    return f"{CH_SITE}/company/{company_number}/filing-history?category=accounts"


def filing_url(company_number: str, transaction_id: str) -> str:
    """One filing, opened as the document itself."""
    return (f"{CH_SITE}/company/{company_number}/filing-history/{transaction_id}"
            "/document?format=pdf&download=0")


def load_filings(path: Path = FILINGS_INDEX) -> dict[str, list[dict]]:
    """{club_id: [filing, ...]}, the latest accounts first."""
    if not path.exists():
        return {}
    out: dict[str, list[dict]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if row.get("transaction_id") and row.get("company_number"):
                out.setdefault(row["club_id"], []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: (r["made_up_date"], r["filing_date"]), reverse=True)
    return out


def filing_for_season(filings: list[dict], season_end_year: int) -> dict | None:
    """
    The filing whose accounts are made up to a date in that year - the
    same rule the parser uses to assign accounts to a season. An amended
    filing for the same year is later, and wins.
    """
    hits = [f for f in filings if (f["made_up_date"] or "")[:4] == str(season_end_year)]
    return max(hits, key=lambda f: f["filing_date"]) if hits else None


def _int_or_none(value: str) -> int | None:
    """Money and counts are whole units; blank means absent, not zero."""
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _text_or_none(value: str) -> str | None:
    text = str(value).strip()
    return text or None


def _validate(row: dict, club_ids: set[str]) -> list[str]:
    """
    Problems that would make a row misleading rather than merely sparse.
    Returned as messages; the caller decides whether to warn or skip.
    """
    problems = []
    disclosure = row["disclosure"]

    if disclosure not in DISCLOSURE_VALUES:
        problems.append(
            f"disclosure {disclosure!r} is not one of {sorted(DISCLOSURE_VALUES)}"
        )

    if club_ids and row["club_id"] not in club_ids:
        problems.append(f"club_id {row['club_id']!r} is not in club_master")

    # A club that didn't disclose can't also have figures - one of the two
    # is wrong, and silently keeping both would misattribute real money to
    # a club that never published any.
    #
    # Which figures that rules out depends on what the regime omits. A
    # small-company filing omits the profit-and-loss and keeps the balance
    # sheet; a club that has not filed, or no longer exists, has neither.
    refused = (PNL_COLUMNS if disclosure == DISCLOSURE_SMALL_COMPANY
               else MONEY_COLUMNS if disclosure != DISCLOSURE_FULL else [])
    present = [c for c in refused if row.get(c) is not None]
    if present:
        problems.append(
            f"disclosure is {disclosure!r} but carries figures: {', '.join(present)}"
        )

    if row.get("staff_costs") is not None and not row.get("staff_costs_definition"):
        problems.append("staff_costs given without staff_costs_definition")

    definition = row.get("staff_costs_definition")
    if definition and definition not in STAFF_COSTS_DEFINITIONS:
        problems.append(
            f"staff_costs_definition {definition!r} is not one of "
            f"{sorted(STAFF_COSTS_DEFINITIONS)}"
        )

    level = row.get("consolidation_level")
    if level and level not in CONSOLIDATION_LEVELS:
        problems.append(
            f"consolidation_level {level!r} is not one of {sorted(CONSOLIDATION_LEVELS)}"
        )

    flags = row.get("flags")
    if flags:
        try:
            parsed = json.loads(flags)
            if not isinstance(parsed, list):
                problems.append("flags must be a JSON array")
        except json.JSONDecodeError:
            problems.append("flags is not valid JSON")

    return problems


def seed_club_finances(conn: sqlite3.Connection, csv_path: Path) -> int:
    """
    Create club_finances (if absent) and load every row from the CSV,
    which is the single source of truth - rows in the table but no longer
    in the CSV are removed, matching seed_club_master().

    A row that fails validation is skipped with a warning rather than
    raising: one bad line shouldn't stop a site build, and a figure that
    can't be trusted is worse than a missing one. Returns the number of
    rows loaded.
    """
    conn.execute(CREATE_CLUB_FINANCES_SQL)
    _migrate(conn)
    conn.commit()

    if not csv_path.exists():
        logger.info("No %s - club_finances left empty", csv_path.name)
        return 0

    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"{csv_path.name} missing columns: {sorted(missing)}")

    club_ids = {
        r[0] for r in conn.execute("SELECT club_id FROM club_master")
    }

    rows, keys, skipped = [], set(), 0
    for _, raw in df.iterrows():
        row = {
            "club_id": str(raw["club_id"]).strip(),
            "season_end_year": _int_or_none(raw["season_end_year"]),
            "disclosure": str(raw["disclosure"]).strip(),
        }
        for col in COLUMNS:
            if col in row:
                continue
            if col in MONEY_COLUMNS or col == "period_months":
                row[col] = _int_or_none(raw[col]) if col in df.columns else None
            else:
                row[col] = _text_or_none(raw[col]) if col in df.columns else None

        if not row["club_id"] or row["season_end_year"] is None:
            logger.warning("Skipping club_finances row with no club_id/season")
            skipped += 1
            continue

        problems = _validate(row, club_ids)
        if problems:
            logger.warning(
                "Skipping club_finances %s/%s: %s",
                row["club_id"], row["season_end_year"], "; ".join(problems),
            )
            skipped += 1
            continue

        keys.add((row["club_id"], row["season_end_year"]))
        rows.append(tuple(row[c] for c in COLUMNS))

    db_keys = {
        (r[0], r[1])
        for r in conn.execute("SELECT club_id, season_end_year FROM club_finances")
    }
    stale = sorted(db_keys - keys)
    if stale:
        logger.warning(
            "Removing %d club_finances row(s) no longer in the CSV", len(stale)
        )
        conn.executemany(
            "DELETE FROM club_finances WHERE club_id = ? AND season_end_year = ?",
            stale,
        )

    placeholders = ",".join("?" * len(COLUMNS))
    conn.executemany(
        f"INSERT OR REPLACE INTO club_finances ({','.join(COLUMNS)})"
        f" VALUES ({placeholders})",
        rows,
    )
    conn.commit()

    if skipped:
        logger.warning("club_finances: %d row(s) skipped as unusable", skipped)
    logger.info("Seeded club_finances with %d rows", len(rows))
    return len(rows)
