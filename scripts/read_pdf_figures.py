#!/usr/bin/env python3
"""
Read the balance sheet out of the OCR text of the scanned accounts.

WHY THIS IS NOT A TAG LOOKUP. 101 of the accounts filings exist only as
scans of paper, and their text comes from OCR (read_pdf_accounts.py). Nothing
in it is tagged: a figure is a run of characters on a line beside a label,
and OCR misreads characters. Gloucester City's 2025 balance sheet comes
through with "41,977,723" where the filing says 1,977,723 - a stray
character - and "1,487,441" where it says 1,467,441 - a 6 read as an 8.

WHY IT CAN STILL BE TRUSTED. A balance sheet is arithmetic, and says the
same thing several ways:

    current assets - creditors within a year     = net current assets
    fixed assets + net current assets            = total assets less current liabilities
    that - creditors after a year - provisions   = net assets
    net assets                                   = total equity
    the items under each heading                 = that heading's total

A misread digit breaks every identity its line takes part in, and the
others go on holding. So a reading is accepted only if the identities it
can check all hold, and at least two of them can be checked. A figure the
identities disagree with is corrected to the value they imply only where
that value is ONE CHARACTER away from what OCR read - one digit wrong, one
dropped, one extra - because that is what an OCR error looks like, and a
coincidence that lands within one character of an identity is not. Every
correction is named in the row's flags.

WHAT IT DOES NOT DO. It never takes a figure from the narrative ("the
company had net current liabilities of £153.6m"): only from inside a
headed balance-sheet block. It never takes the prior-year column as a row
of its own - the brief is more clubs, not more history - though that
column's identities are checked too, and a block whose prior year does
not balance is still accepted if the current year does.

    python3 scripts/read_pdf_figures.py            # data/companies/pdf/*.txt
"""

import argparse
import csv
import itertools
import logging
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = PROJECT_ROOT / "data" / "companies" / "pdf"
FIGURES = PDF_DIR / "figures.tsv"

logger = logging.getLogger("read_pdf_figures")

# ── finding the balance sheet ──────────────────────────────────────────────

HEADING = re.compile(
    r"(?i)^\W{0,6}(?P<kind>consolidated|group|company|parent company|parent)?\s*"
    r"(?:balance\s+sheets?|statements?\s+of\s+financial\s+position)\b(?P<rest>.*)$")
# The statements that follow a balance sheet, which end its block.
NEXT_STATEMENT = re.compile(
    r"(?i)statements?\s+of\s+changes\s+in\s+equity|cash\s*flow|notes\s+to\s+the|"
    r"income\s+statement|profit\s+and\s+loss\s+account|statement\s+of\s+comprehensive|"
    r"were\s+approved\s+by\s+the\s+board|the\s+notes\s+on\s+pages|"
    # The statements a small company prints under its balance sheet,
    # whose words otherwise read as reserves lines.
    r"entitled\s+to\s+exemption|members\s+have\s+not\s+required|section\s+4(?:44|76|77)|"
    r"directors?\s+acknowledges?|"
    r"(?:consolidated|company)\s+balance\s+sheet")
YEARS = re.compile(r"\b(20\d\d)\b")

# ── reading a figure ───────────────────────────────────────────────────────

# OCR's usual substitutions inside a figure. Applied only to the numeric
# tail of a line, never to its label.
OCR_DIGITS = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "§": "5", "S": "5",
                            "l": "1", "I": "1", "|": "1", "B": "8"})
NUMBER = re.compile(r"[\(\{\[]?\s*-?\d{1,3}(?:[,.]\s?\d{3})+\s*[\)\}\]]?"
                    r"|[\(\{\[]?\s*-?\d+\s*[\)\}\]]?"
                    r"|(?<![\w-])[-–—](?![\w-])")


def _tail(line: str) -> tuple[str, str]:
    """
    Split a line into its label and its numeric tail: everything after
    the last run of two or more letters. "Debtors: amounts falling due
    after more 14 14,431 57,296" -> label up to "more", tail "14 14,431
    57,296". A label word OCR has mangled into a letter or two stays in
    the tail, where the parser ignores it.
    """
    last = None
    for m in re.finditer(r"[A-Za-z]{2,}", line):
        last = m
    if last is None:
        return "", line
    return line[:last.end()], line[last.end():]


def numbers(tail: str) -> list[int]:
    """
    The figures in a line's numeric tail, in order. A bracket on either
    side makes a figure negative, because OCR drops one of a pair as
    often as it keeps both: "121,384)" is minus 121,384. A lone dash is
    a nil.
    """
    tail = tail.translate(OCR_DIGITS)
    out = []
    for m in NUMBER.finditer(tail):
        token = m.group(0)
        if re.fullmatch(r"[-–—]", token.strip()):
            out.append(0)
            continue
        digits = re.sub(r"[^\d]", "", token)
        if not digits:
            continue
        value = int(digits)
        if re.search(r"[\(\{\[]", token) or re.search(r"[\)\}\]]", token) or token.strip().startswith("-"):
            value = -value
        out.append(value)
    return out


def _values(line: str, columns: int = 2, pick: int | None = None) -> tuple[str, list[int | None]] | None:
    """
    (label, [current, prior]) - notes precede the values, so the values
    are the last two figures. A labelled line with only one figure keeps
    it as the current year: OCR loses the prior-year column often enough
    ("NET LIABILITIES (128,553,760)") that dropping the line would lose
    the current year with it.

    pick reads a balance sheet printed with the group and the company side
    by side - four columns, group then company. 0 takes the group's pair,
    1 the company's. A line with fewer than four figures there cannot say
    whose they are, so it is not read.
    """
    label, tail = _tail(line)
    nums = numbers(tail)
    if pick is not None:
        if len(nums) < 4:
            return None
        return label, nums[-4:][2 * pick:2 * pick + 2]
    if len(nums) >= columns:
        return label, nums[-columns:]
    if len(nums) == 1 and _norm(label) and not re.fullmatch(r"\s*\d{1,2}\s*", tail.translate(OCR_DIGITS)):
        return label, [nums[0], None]
    return None


def _alternates(line: str, pick: int | None) -> list[list[int]]:
    """
    A second reading of a four-column line, for the identities to choose
    between: OCR leaves a stray dash between the columns ("Shareholders'
    funds 126,465 127,852 - 147,322 147,520"), and the last four figures
    are then the wrong four. Offered only where dropping the nils leaves
    exactly four.
    """
    if pick is None:
        return []
    nums = numbers(_tail(line)[1])
    figures = [n for n in nums if n]
    if len(nums) > 4 and len(figures) == 4:
        return [figures[2 * pick:2 * pick + 2]]
    return []


# ── what each line is ──────────────────────────────────────────────────────

def _norm(label: str) -> str:
    text = re.sub(r"[^a-z ]", " ", label.lower())
    return " ".join(text.split())


LINES = [
    # OCR's spellings included: Malvern Town's "Net current liabilittes".
    ("NCA", re.compile(r"net current (assets|liabil\w*)")),
    # Blackburn's filing calls it "total current assets less current
    # liabilities", which is not what it is but is where it is.
    ("TALCL", re.compile(r"total (current )?assets less current")),
    ("CAF", re.compile(r"(after|more than) (more than )?one year|after one year")),
    ("CL", re.compile(r"within one year|creditors due within|current liabilities$")),
    ("PRV", re.compile(r"^provisions?( for liabilities)?( and charges)?$|^provisions? for")),
    # "Net (liabilities)/assets" normalises to "net liabilities assets".
    ("NA", re.compile(r"^(total )?net (assets|liabilities|deficit)( (assets|liabilities))?$"
                      r"|^net (assets|liabilities) (deficit|surplus)")),
    ("EQ", re.compile(r"total (equity|shareholders|members|funds|capital)|shareholders? ?(funds|deficit|equity)"
                      r"|capital employed|equity shareholders")),
    ("FA", re.compile(r"^(total )?fixed assets$|^non current assets$")),
    ("CA", re.compile(r"^(total )?current assets$")),
    ("SC", re.compile(r"called up share capital|^share capital$|^ordinary share capital")),
]
SECTION = [
    ("fixed", re.compile(r"^fixed assets|^non current assets")),
    ("current", re.compile(r"^current assets")),
    ("creditors", re.compile(r"^creditors")),
    ("reserves", re.compile(r"^capital and reserves|^equity$|^represented by")),
]
LIABILITY = re.compile(r"creditor|provision|deferred|pension|accrual|grant|liabilit|loan|lease|"
                       r"\btax|borrow|obligation|payable|income in advance")

# Lines under a heading whose total the heading's identity checks.
COMPONENT = {
    "fixed": {"intangible": re.compile(r"intangible"), "tangible": re.compile(r"^tangible|property plant"),
              "investments": re.compile(r"investment")},
    "current": {"stocks": re.compile(r"stock|inventor"), "debtors": re.compile(r"debtor|receivable"),
                "cash": re.compile(r"cash")},
}


def parse_block(lines: list[str], pick: int | None = None) -> dict:
    """
    Candidate values, per year column, for every line the identities use.

    A variable can have several candidates, because OCR moves a subtotal
    onto the line below: West Ham's fixed-asset total of 258,616 comes out
    on the "Current assets" heading line. Both readings are offered and the
    identities choose.

    Lines between total assets less current liabilities and net assets
    that are not long-term creditors or provisions - deferred grants,
    pension deficits, accruals in the old format - are collected as OTHER,
    because the net-assets identity has to subtract every one of them.
    """
    cands: dict[str, list[tuple]] = {}
    comps: dict[str, dict[str, tuple]] = {"fixed": {}, "current": {}, "reserves": {}}
    other: list[tuple] = []
    section = None
    pending = ""
    after_talcl = False

    def add(var, vals):
        if tuple(vals) not in cands.setdefault(var, []):
            cands[var].append(tuple(vals))

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        parsed = _values(line, pick=pick)
        label = _norm(_tail(line)[0])
        if parsed is None:
            # A label carried onto the next line: "Creditors - amounts
            # falling" / "due within one year 15 (415,196)". A heading is
            # not carried - "Notes £ £ £" and "FIXED ASSETS" are not the
            # start of the next line's label.
            if label:
                heading = False
                for name, rx in SECTION:
                    if rx.search(label):
                        section = name
                        # A heading is the bare words. "Creditors: amounts
                        # falling due within" starts like one and is the
                        # first half of a label.
                        heading = len(label.split()) <= 3
                pending = "" if heading or len(label) >= 60 else label
            continue
        # Only a line that visibly continues its predecessor takes the
        # carried label: lower-case, or one of the words a wrapped
        # creditors line starts with.
        first = re.search(r"[A-Za-z]", line)
        continues = bool(first) and (first.group(0).islower() or re.match(
            r"(?i)\W*(due|amounts?|one year|than|after|within|more|falling|liabilities)\b", line))
        full = _norm((pending + " " + label).strip()) if pending and continues else label
        pending = ""
        vals = parsed[1]

        matched = None
        for var, rx in LINES:
            if not rx.search(full):
                continue
            # "Amounts falling due after one year" under Current assets is
            # a debtor, whatever its own line says.
            if var in ("CL", "CAF") and ("debtor" in full or (section == "current" and "creditor" not in full)):
                continue
            matched = var
            break
        if matched:
            add(matched, vals)
            for alt in _alternates(line, pick):
                add(matched, alt)
            # Share capital is a reserves line too: the reserves' sum is
            # what verifies it, so it has to be in the sum.
            if matched == "SC":
                comps["reserves"].setdefault(full, tuple(vals))
            if matched == "CA" and section == "fixed":
                add("FA", vals)          # the heading line, carrying the previous total
            for name, rx in SECTION:
                if rx.search(full):
                    section = name
            if matched in ("NCA", "CL"):
                section = "creditors"
            if matched == "TALCL":
                after_talcl = True
            if matched in ("NA", "EQ"):
                after_talcl = False
            continue
        if not full:
            # An unlabelled subtotal: the total of the section it closes.
            if section == "fixed":
                add("FA", vals)
            elif section == "current":
                add("CA", vals)
            elif section == "reserves":
                add("EQ", vals)
            continue
        for name, rx in SECTION:
            if rx.search(full):
                section = name
                if name == "reserves":
                    after_talcl = False
        # Only what reads as a liability: OCR debris and a stray subtotal
        # between the two totals would otherwise be subtracted as debt.
        if after_talcl and section != "reserves" and LIABILITY.search(full):
            other.append(tuple(vals))
            continue
        if section in COMPONENT:
            for comp, rx in COMPONENT[section].items():
                if rx.search(full):
                    comps[section].setdefault(comp, tuple(vals))
        elif section == "reserves" and len(full.split()) <= 6:
            comps["reserves"].setdefault(full, tuple(vals))
            if "share capital" in full:
                add("SC", vals)
    if other:
        cands["OTHER"] = [tuple(sum(abs(v[i]) for v in other if v[i] is not None) for i in range(2))]
    # A section that prints its items and no subtotal - Gloucester City's
    # fixed assets are one line, "Tangible assets" - has that sum as its
    # total.
    for var, sect in (("FA", "fixed"), ("CA", "current")):
        items = list(comps[sect].values())
        if items and all(None not in v for v in items):
            total = tuple(sum(v[i] for v in items) for i in range(2))
            if total not in cands.get(var, []):
                cands.setdefault(var, []).append(total)
    return {"cands": cands, "comps": comps}


# ── the identities ─────────────────────────────────────────────────────────

def _one_char(a: int, b: int) -> bool:
    """Is b one OCR error away from a - one digit changed, dropped or added?"""
    sa, sb = str(abs(a)), str(abs(b))
    if sa == sb:
        return True
    if len(sa) == len(sb):
        return sum(x != y for x, y in zip(sa, sb)) == 1
    if abs(len(sa) - len(sb)) == 1:
        short, long_ = (sa, sb) if len(sa) < len(sb) else (sb, sa)
        return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))
    return False


def _identities(v: dict) -> list[tuple[str, list[str], callable]]:
    """(name, the variables it uses, a function giving the residual)."""
    out = []
    if {"CA", "CL", "NCA"} <= v.keys():
        out.append(("I1", ["CA", "CL", "NCA"], lambda x: x["CA"] - abs(x["CL"]) - x["NCA"]))
    if {"FA", "NCA", "TALCL"} <= v.keys():
        out.append(("I2", ["FA", "NCA", "TALCL"], lambda x: x["FA"] + x["NCA"] - x["TALCL"]))
    end = "NA" if "NA" in v else "EQ" if "EQ" in v else None
    if "TALCL" in v and end:
        out.append(("I3", ["TALCL", "CAF", "PRV", "OTHER", end],
                    lambda x, e=end: x["TALCL"] - abs(x.get("CAF", 0)) - abs(x.get("PRV", 0))
                    - abs(x.get("OTHER", 0)) - x[e]))
    if "NA" in v and "EQ" in v:
        out.append(("I4", ["NA", "EQ"], lambda x: x["NA"] - x["EQ"]))
    return out


def _implied(name: str, var: str, x: dict) -> int | None:
    """The value of `var` that would make identity `name` hold, the others as read."""
    if name == "I1":
        return {"CA": abs(x["CL"]) + x["NCA"], "CL": x["CA"] - x["NCA"],
                "NCA": x["CA"] - abs(x["CL"])}.get(var)
    if name == "I2":
        return {"FA": x["TALCL"] - x["NCA"], "NCA": x["TALCL"] - x["FA"],
                "TALCL": x["FA"] + x["NCA"]}.get(var)
    if name == "I3":
        end = "NA" if "NA" in x else "EQ"
        rest = abs(x.get("CAF", 0)) + abs(x.get("PRV", 0)) + abs(x.get("OTHER", 0))
        return {"TALCL": x[end] + rest, end: x["TALCL"] - rest}.get(var)
    if name == "I4":
        return {"NA": x["EQ"], "EQ": x["NA"]}.get(var)
    return None


def _held(x: dict, tolerance: int) -> tuple[int, int]:
    ids = _identities(x)
    held = sum(1 for _, _, f in ids if abs(f(x)) <= tolerance)
    return held, len(ids)


def _corrections(x: dict, tolerance: int, depth: int, fixed: tuple = ()) -> list[tuple[dict, tuple]]:
    """
    Every way of correcting up to `depth` figures, each to a value an
    identity implies and one character from what OCR read, that leaves
    all the identities holding. Searched whole, not greedily: Gloucester
    City's fixed assets can be nudged to fit a misread total, and only
    the search shows that the total is what was misread.
    """
    held, total = _held(x, tolerance)
    if held == total:
        return [(x, fixed)]
    if depth == 0:
        return []
    out = []
    for name, vs, f in _identities(x):
        if abs(f(x)) <= tolerance:
            continue
        for var in vs:
            if var not in x or var in fixed:
                continue
            target = _implied(name, var, x)
            if target is None or target == x[var] or not _one_char(x[var], target):
                continue
            out.extend(_corrections(dict(x, **{var: target}), tolerance, depth - 1, fixed + (var,)))
    return out


def solve(cands: dict[str, list[int]], tolerance: int = 1, max_fixes: int = 2) -> dict:
    """
    One year column's figures, if the identities accept them.

    For every combination of candidates, the corrections (at most
    `max_fixes`, each one OCR character) that make every identity hold
    are searched for. The answer with the fewest corrections wins, and it
    must be the only answer with that few: two different balance sheets
    that both add up is a reading nobody should trust. Accepted only if at
    least two identities could be checked.
    """
    names = sorted(cands)
    if not names:
        return {"ok": False, "reason": "no balance-sheet lines"}
    best: dict[tuple, tuple] = {}
    nearest = None
    for combo in itertools.product(*(cands[n] for n in names)):
        x = dict(zip(names, combo))
        held, total = _held(x, tolerance)
        if nearest is None or held - total > nearest[0]:
            nearest = (held - total, x)
        for result, fixes in _corrections(x, tolerance, max_fixes):
            key = tuple(sorted(result.items()))
            if key not in best or len(fixes) < len(best[key][1]):
                best[key] = (result, fixes)
    if not best:
        x = nearest[1]
        failing = [n for n, _, f in _identities(x) if abs(f(x)) > tolerance]
        return {"ok": False, "reason": "does not balance: " + ",".join(failing), "values": x}

    def verified(x):
        """Only the figures some checkable identity uses: the rest prove nothing."""
        used = {v for _, vs, _ in _identities(x) for v in vs if v in x}
        return {k: v for k, v in x.items() if k in used}

    projected: dict[tuple, tuple] = {}
    for result, fixes in best.values():
        key = tuple(sorted(verified(result).items()))
        if key not in projected or len(fixes) < len(projected[key][1]):
            projected[key] = (result, fixes)
    fewest = min(len(f) for _, f in projected.values())
    answers = [(r, f) for r, f in projected.values() if len(f) == fewest]
    if len(answers) > 1:
        return {"ok": False, "reason": f"{len(answers)} different readings add up",
                "values": answers[0][0]}
    x, fixes = answers[0]
    ids = _identities(x)
    if len(ids) < 2:
        return {"ok": False, "reason": f"only {len(ids)} identity checkable", "values": x}
    return {"ok": True, "values": verified(x), "fixes": list(fixes),
            "checks": [n for n, _, _ in ids]}


def _component_total(comps: dict, column: int, total: int, tolerance: int) -> bool:
    values = [v[column] for v in comps.values()]
    return bool(values) and None not in values and abs(sum(values) - total) <= tolerance


# ── a document ─────────────────────────────────────────────────────────────

NET_CURRENT = re.compile(r"(?i)net\W+current\W+\(?(assets|liabil)")
HEADING_ANYWHERE = re.compile(r"(?i)(balance\s+sheets?|statements?\s+of\s+financial\s+position)")


def blocks(text: str) -> list[dict]:
    """
    Every balance-sheet block in a document's text.

    Found from the "net current" line rather than from the heading,
    because headings come through OCR in every shape - "31 Consolidated
    Statement of Financial Position" with its page number, "Abridged
    Balance Sheet", a company name run into the same line - while a net
    current line with two figures on it is the balance sheet and nothing
    else. Narrative ("the company had net current liabilities of
    £153.6m") carries one figure, and is passed over.

    The block is from the nearest heading above that line to the next
    statement below it, and its level - group, company or a single
    entity's - comes from that heading's own words.
    """
    lines = text.splitlines()
    out, used = [], set()
    for j, line in enumerate(lines):
        if not NET_CURRENT.search(line):
            continue
        label, tail = _tail(line)
        if len(numbers(tail)) < 2 or len(label.split()) > 8:
            continue
        head = None
        for i in range(j - 1, max(-1, j - 55), -1):
            h = lines[i]
            if HEADING_ANYWHERE.search(h) and len(h.split()) <= 12 and not re.search(
                    r"(?i)\b(date|events|recognised|value of|funding)\b", h):
                head = i
                break
        unlabelled = False
        if head is None:
            # No heading came through OCR - Everton's balance sheet runs
            # from a page header straight into the columns. Start at the
            # fixed-assets line instead, and say the level is not known.
            for i in range(j - 1, max(-1, j - 40), -1):
                if re.match(r"(?i)^\W*(fixed assets|non[\s-]*current assets)\b", lines[i]):
                    head, unlabelled = max(0, i - 4), True
                    break
        if head is None or head in used:
            continue
        used.add(head)
        body = []
        for later in lines[head + 1:head + 100]:
            # A heading carries no figures. "Profit and loss account
            # (233,557) (125,296)" is a reserves line, not the start of
            # the next statement.
            if len(body) > j - head + 2 and NEXT_STATEMENT.search(later) \
                    and len(numbers(_tail(later)[1])) < 2:
                break
            body.append(later)
        heading = lines[head].lower()
        header = " ".join(body[:14])
        years = [int(y) for y in YEARS.findall(header)]
        scale = 1000 if re.search(r"£\s*['’`]?\s*0{3}|£\s*000|£k\b|'000", header, re.I) else \
            1_000_000 if re.search(r"£\s*m\b", header, re.I) else 1
        level = "unlabelled" if unlabelled else \
            "group" if re.search(r"consolidated|group", heading) else \
            "company" if re.search(r"company|parent", heading) else "plain"
        block = {"line": head, "level": level, "years": years[:2], "scale": scale, "body": body}
        # Group and company side by side under one heading - Arsenal's
        # "Group Company / 2025 2024 2025 2024". Read as the two balance
        # sheets it is; the last two columns alone are the parent's, and
        # were once taken for the group's.
        if re.search(r"(?i)\bgroup\b", header) and re.search(r"(?i)\bcompany\b", header) \
                and level in ("plain", "unlabelled"):
            if len(years) >= 4:
                out.append(dict(block, level="group", pick=0))
                out.append(dict(block, level="company", pick=1))
            else:
                out.append(dict(block, level="mixed"))
            continue
        out.append(block)
    return out


def read_text(text: str, made_up_year: int | None) -> dict:
    """
    The figures one filing's text supports, at each level it shows.

    Returns {"levels": {level: {"fields", "fixes", "checks", "scale"}},
    "rejected": [reasons]}. A level is "group" for a consolidated balance
    sheet, "company" for the parent's own, "plain" for a filing with one.
    """
    out = {"levels": {}, "rejected": []}
    found = blocks(text)
    # Two balance sheets whose headings OCR lost, in a filing whose
    # contents page lists a consolidated one and then a company one:
    # statements are printed in contents order, so that order levels them.
    # Everton's and Norwich City's filings are both like this.
    if len(found) == 2 and all(b["level"] == "unlabelled" for b in found):
        # A contents line: the title with a page number on either side -
        # "Consolidated Balance Sheet 18", "31 Consolidated Statement of
        # Financial Position".
        contents = [m.group(0).lower() for m in re.finditer(
            r"(?im)^\W{0,4}(?:\d{1,3}\s+)?\W{0,3}(consolidated|company|group|parent)[^\n]{0,25}"
            r"(balance\s+sheet|statement\s+of\s+financial\s+position)\W{0,4}(?:\d{1,3})?\W{0,3}$", text)
            if re.search(r"(?:^\W{0,4}\d{1,3}\s)|(?:\d{1,3}\W{0,3}$)", m.group(0))]
        kinds = ["group" if re.search(r"consolidated|group", c) else "company" for c in contents]
        if kinds[:2] == ["group", "company"]:
            found[0]["level"], found[1]["level"] = "group", "company"
            for b in found:
                b["from_contents"] = True
    for b in found:
        if b["level"] in out["levels"]:
            continue
        # An unlabelled block is used only as a filing's one balance sheet:
        # beside a labelled one it could be either level, and guessing
        # which is the guess this parser refuses to make.
        if b["level"] == "unlabelled" and len(found) > 1:
            out["rejected"].append("unlabelled block beside another - level unknown")
            continue
        if b["level"] == "mixed":
            out["rejected"].append("group and company columns that cannot be told apart")
            continue
        # The block must be for the year these accounts are made up to.
        if made_up_year and b["years"] and b["years"][0] != made_up_year:
            out["rejected"].append(f"{b['level']} block for {b['years'][0]}, not {made_up_year}")
            continue
        parsed = parse_block(b["body"], b.get("pick"))
        if not parsed["cands"]:
            continue
        def column(i):
            out_ = {}
            for k, vs in parsed["cands"].items():
                values = [v[i] for v in vs if v[i] is not None]
                if k != "SC" and values:
                    out_[k] = list(dict.fromkeys(values))
            return out_
        cur, prior = column(0), column(1)
        # A heading the block has no line for at all is a nil, not unknown:
        # a club with no fixed assets prints none.
        if "FA" not in cur and not parsed["comps"]["fixed"]:
            cur["FA"], prior["FA"] = [0], [0]
        result = solve(cur)
        if not result["ok"]:
            out["rejected"].append(f"{b['level']}: {result['reason']}")
            continue
        prior_result = solve(prior)
        x, s = result["values"], b["scale"]
        fields = {
            "net_current_assets": x.get("NCA"),
            "total_assets_less_current_liabilities": x.get("TALCL"),
            "creditors_within_year": abs(x["CL"]) if "CL" in x else None,
            "creditors_after_year": abs(x["CAF"]) if "CAF" in x else None,
            "current_assets": x.get("CA"),
            "fixed_assets": x.get("FA"),
            "net_assets": x.get("NA", x.get("EQ")),
        }
        comps = parsed["comps"]
        # Components only where they add up to the total they sit under.
        if "FA" in x and _component_total(comps["fixed"], 0, x["FA"], 1):
            for comp, field in (("intangible", "intangible_assets"), ("tangible", "tangible_assets")):
                if comp in comps["fixed"]:
                    fields[field] = comps["fixed"][comp][0]
        if "CA" in x and _component_total(comps["current"], 0, x["CA"], 1):
            for comp, field in (("debtors", "debtors"), ("cash", "cash")):
                if comp in comps["current"]:
                    fields[field] = comps["current"][comp][0]
        equity = x.get("EQ", x.get("NA"))
        reserves = {k: v for k, v in comps["reserves"].items()
                    if not re.search(r"total|funds|deficit|equity", k)}
        if equity is not None and _component_total(reserves, 0, equity, 1):
            share = next((v[0] for k, v in reserves.items() if "share capital" in k), None)
            if share is not None:
                fields["share_capital"] = share
        fields = {k: v * s for k, v in fields.items() if v is not None}
        out["levels"][b["level"]] = {
            "fields": fields, "fixes": result["fixes"], "checks": result["checks"],
            "scale": s, "prior_balances": prior_result["ok"],
            "from_contents": b.get("from_contents", False),
            "prior_net_assets": ((prior_result["values"].get("NA", prior_result["values"].get("EQ")) or 0) * s
                                 if prior_result["ok"] and ("NA" in prior_result["values"]
                                                            or "EQ" in prior_result["values"]) else None),
        }
    return out


# ── the notes: tables that add up ──────────────────────────────────────────

def summed_table(lines: list[str], start: int, span: int = 18) -> dict | None:
    """
    Items, then a total equal to their sum, read from the lines after
    `start`. The same rule as the balance sheet, at the scale of a note:
    Arsenal's playing, training, commercial and ground staff - 101, 90,
    564 and 116 - make the 871 printed under them, and both years agree,
    so the 871 is accepted. A table whose items do not reach its total is
    not.

    Two-column tables only. A group-and-company note prints four columns,
    and which pair is which is a guess this does not make.
    """
    items, header_scale = [], None
    # The unit can be printed above the table's first line as well as
    # below it - Arsenal's "£000" sits over "Staff costs:".
    for line in lines[max(0, start - 3):start + 1]:
        if re.search(r"£\s*['’`°7]?\s*0{3}|£\s*000|'000", line):
            header_scale = 1000
    for line in lines[start + 1:start + 1 + span]:
        if re.search(r"£\s*['’`°]?\s*0{3}|£\s*000|'000", line):
            header_scale = 1000
        label, tail = _tail(line)
        nums = numbers(tail)
        lab = _norm(label)
        if YEARS.fullmatch(line.strip().split()[0]) if line.strip() else False:
            continue
        if not nums:
            if items and len(lab.split()) > 6:
                break                     # prose: the table has ended
            continue
        if len(nums) > 3:
            return None
        vals = nums[-2:] if len(nums) >= 2 else [nums[0], None]
        if all(1990 <= abs(v) <= 2100 for v in vals if v is not None) and not lab:
            continue                      # a row of years
        if len(items) >= 2:
            cur = sum(i[1] for i in items)
            prior = [i[2] for i in items]
            prior_sum = sum(prior) if None not in prior else None
            if abs(cur - vals[0]) <= 1 and (vals[1] is None or prior_sum is None
                                            or abs(prior_sum - vals[1]) <= 1):
                if not lab or re.search(r"total|^average", lab):
                    return {"items": items, "total": (vals[0], vals[1]), "scale": header_scale}
        if lab and not re.search(r"^total", lab):
            items.append((lab, vals[0], vals[1]))
        elif re.search(r"^total", lab):
            return None                   # a total the items do not reach
    return None


EMPLOYEES = re.compile(r"(?i)average\s+(?:monthly\s+|weekly\s+)?number\s+of\s+"
                       r"(?:persons|employees|people|staff)")
EMPLOYEES_SENTENCE = re.compile(
    r"(?is)average\s+(?:monthly\s+)?number\s+of\s+(?:persons|employees|people|staff)"
    r"[^.]{0,160}?\b(?:was|were|is|amounted\s+to)\s*:?\s*(\d[\d,]*)\s*"
    r"\(\s*(?:20\d\d|prior year|previous year)?\s*[:\-–—]?\s*(\d[\d,]*)\s*\)")
STAFF_COSTS = re.compile(r"(?i)^\W*(?:\d+\.?\s+)?staff\s+costs|staff costs.{0,60}(?:were|as follows|comprise)")


def read_notes(text: str, scale: int = 1) -> dict:
    """
    Headcount and staff costs from the notes, each accepted only from a
    table whose items add up to its total - or, for headcount, from the
    sentence form "was 23 (2024: 21)", which states both years and is
    flagged as unchecked.
    """
    lines = text.splitlines()
    out = {}
    for i, line in enumerate(lines):
        if "employees" not in out and EMPLOYEES.search(line):
            table = summed_table(lines, i)
            if table and table["total"][0] and 0 < table["total"][0] < 20000:
                out["employees"] = table["total"][0]
                out["employees_check"] = f"sum of {len(table['items'])}"
        if "staff_costs" not in out and STAFF_COSTS.search(line):
            table = summed_table(lines, i)
            if table and any("wage" in lab or "salar" in lab for lab, _, _ in table["items"]):
                # Where the note prints no unit, it shares the balance
                # sheet's: accounts are presented in one.
                out["staff_costs"] = table["total"][0] * (table["scale"] or scale)
                out["staff_costs_check"] = f"sum of {len(table['items'])}"
    if "employees" not in out:
        m = EMPLOYEES_SENTENCE.search(text)
        if m:
            value = int(m.group(1).replace(",", ""))
            if 0 < value < 20000:
                out["employees"] = value
                out["employees_check"] = "sentence"
    return out


def document_facts(text: str) -> dict:
    """
    What the filing says about itself, read the same way the iXBRL facts
    are where the scan allows: whether it is full accounts or the
    small-company regime, whether the profit-and-loss was withheld under
    section 444, and any going-concern warning, using the parser's own
    wording rules so a negated sentence is not a flag.
    """
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from parse_club_accounts import _clean, _going_concern

    flat = _clean(text)
    withheld = bool(re.search(r"(?i)section\s+444[^.]{0,160}(not\s+(been\s+)?(delivered|filed)|elected\s+not)"
                              r"|(not\s+(been\s+)?(delivered|filed))[^.]{0,120}section\s+444", flat))
    pnl = bool(re.search(r"(?im)^\W{0,8}(consolidated\s+|group\s+)?(income\s+statement|"
                         r"profit\s+and\s+loss\s+account|statement\s+of\s+comprehensive\s+income)",
                         text)) and bool(re.search(r"(?im)^\W{0,4}(turnover|revenue)\b[^\n]*\d", text))
    return {
        "_disclosure": "full" if pnl and not withheld else "small_company",
        "_pnl_withheld": "yes" if withheld else "",
        "_going_concern": _going_concern(flat) or "",
    }


FIGURE_COLUMNS = ["club_id", "file", "document", "made_up_date", "level", "field", "value",
                  "fixes", "checks", "scale", "from_contents"]


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=str(PDF_DIR))
    parser.add_argument("--out", default=str(FIGURES))
    args = parser.parse_args()
    directory = Path(args.dir)
    census = {r["file"][:-4]: r for r in csv.DictReader(
        (directory / "census.tsv").open(encoding="utf-8"), delimiter="\t")}

    rows, read, rejected, readings = [], 0, [], {}
    for stem, meta in sorted(census.items()):
        path = directory / f"{stem}.txt"
        if not path.exists():
            continue
        year = int(meta["made_up_date"][:4]) if meta.get("made_up_date") else None
        result = read_text(path.read_text(encoding="utf-8"), year)
        if not result["levels"]:
            rejected.append((stem, "; ".join(result["rejected"]) or "no balance sheet found"))
            continue
        read += 1
        readings[stem] = result["levels"]
        # The notes describe the reporting entity as its accounts present
        # it: the group where there is one, else the only balance sheet.
        primary = next((lv for lv in ("group", "plain", "company", "unlabelled")
                        if lv in result["levels"]), None)
        notes = read_notes(path.read_text(encoding="utf-8"),
                           result["levels"][primary]["scale"] if primary else 1)
        if primary and notes:
            lv = result["levels"][primary]
            for field in ("employees", "staff_costs"):
                if field in notes:
                    lv["fields"][field] = notes[field]
                    lv["checks"] = lv["checks"] + [f"{field}:{notes[field + '_check']}"]
        for field, value in document_facts(path.read_text(encoding="utf-8")).items():
            rows.append({"club_id": meta["club_id"], "file": stem, "document": meta["document"],
                         "made_up_date": meta["made_up_date"], "level": "document",
                         "field": field, "value": value, "fixes": "", "checks": "",
                         "scale": "", "from_contents": ""})
        for level, r in result["levels"].items():
            for field, value in sorted(r["fields"].items()):
                rows.append({"club_id": meta["club_id"], "file": stem, "document": meta["document"],
                             "made_up_date": meta["made_up_date"], "level": level, "field": field,
                             "value": value, "fixes": ",".join(r["fixes"]),
                             "checks": ",".join(r["checks"]), "scale": r["scale"],
                             "from_contents": "yes" if r["from_contents"] else ""})
    out = Path(args.out)
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, FIGURE_COLUMNS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    logger.info("%d of %d filings gave a balance sheet that adds up -> %s",
                read, len(census), out.name)

    # The independent check. A club's latest filing prints the year before
    # as its comparative column, and that year has its own filing, read
    # separately a year earlier. Where both were read, the two net-assets
    # figures must agree - unless the latest filing restated the year.
    # Paired by the year each is made up to, not by filing order: Malvern
    # Town filed the same 2025 accounts twice, original and amendment.
    by_year = {}
    for stem, levels in readings.items():
        year = (census[stem].get("made_up_date") or "")[:4]
        if year.isdigit():
            by_year[(census[stem]["club_id"], int(year))] = levels
    agree, differ = 0, []
    for (club, year), levels in sorted(by_year.items()):
        earlier = by_year.get((club, year - 1))
        if not earlier:
            continue
        for level, r in levels.items():
            if level in earlier and r["prior_net_assets"] is not None:
                theirs = earlier[level]["fields"].get("net_assets")
                if theirs is None:
                    continue
                if theirs == r["prior_net_assets"]:
                    agree += 1
                else:
                    differ.append(f"{club} {level}: {r['prior_net_assets']:,} in the latest, "
                                  f"{theirs:,} in its own filing")
    logger.info("cross-check: prior-year net assets agree with the earlier filing's own in "
                "%d of %d pairs (a restated year is expected to differ)", agree, agree + len(differ))
    for line in differ:
        logger.info("    %s", line)
    for stem, reason in rejected:
        logger.info("    %-36s %s", stem, reason[:110])


if __name__ == "__main__":
    main()
