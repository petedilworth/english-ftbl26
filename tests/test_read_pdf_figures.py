"""
Reading a balance sheet out of OCR text.

The texts below are the real shapes from the scanned filings, with their
real OCR errors. What is pinned: a reading is accepted only if its
identities hold; a figure is corrected only to a value one character from
what OCR read, and only if exactly one balance sheet then adds up; and a
figure no identity checks is never output.
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import finances                                          # noqa: E402
import parse_club_accounts as pca                        # noqa: E402
import read_pdf_figures as rpf                           # noqa: E402

# Gloucester City's 2025 filing as OCR read it: "41,977,723" for
# 1,977,723, and "(1,487,441)" for (1,467,441).
GLOUCESTER = """Balance Sheet :
30 June 2025 ;
2025 2024
Notes £ £ £
FIXED ASSETS
Tangible assets 4 479,078 501,461
CURRENT ASSETS
Stocks 1,000 1,000
Debtors 5 24,414 12,186
Cash at bank 5,790 182
31,204 13,368
CREDITORS
Amaunts falling due within one year 6 41,977,723 4,808,718
NET CURRENT LIABILITIES (1,946,519) (1,795,348)
TOTAL ASSETS LESS CURRENT
- LIABILITIES (1,487,441) (1,293,887)
CAPITAL AND RESERVES
Called up share capital 15,000 15,000
Share premium 235,050 235,050
Retained earnings (1,717,491) (1,543,937)
(1,467,441) (1,293,887)
The company is entitled to exemption from audit under Section 477 of the Companies Act 2006.
"""

# West Ham's, in £000, with the fixed-asset total carried onto the
# "Current assets" heading line.
WEST_HAM = """BALANCE SHEET ;
as at 31 May 2025
Note(s) 2025 2024
: £000 £000 £000 £000
Fixed assets
Intangible assets 11 223,152 213,949
Tangible assets 12 35,464 26,843
Current assets 258,616 240,792
Stocks : 13 1,818 2,895
Debtors: amounts falling due after more 14 14,431 57,296
than one year
Debtors: amounts falling due within 14 20,784 54,014
one year
Cash at bank and in hand 422 33,046
37,455 147,251
Creditors - amounts falling
due within one year 15 (415,196) (393,719)
Net current liabilities . (377,741) (246,468)
Total assets less current liabilities : (119,125) (5,676)
Creditors — amounts falling
* due after more than one year 15 (90,821) (93,207)
Provisions for liabilities 19,20 (6,676) (9,478)
Net liabilities (216,622) (108,361)
Capital and reserves
Called up share capital 21 5,500 5,500
Share premium account : 22 _ 4,847 4,847
Revaluation reserve 23 6,588 6,588
Profit and loss account 24 (233,557) (125,296)
Total shareholders' deficit 25 (216,622) (108,361)
The notes on pages 31 to 52 are an integral part of these financial statements.
"""


# ── reading a figure ───────────────────────────────────────────────────────

def test_ocr_s_bracket_damage_still_reads_as_negative():
    assert rpf.numbers("(153,623,451) { 142,522,425)") == [-153623451, -142522425]
    assert rpf.numbers("121,384) 2,776") == [-121384, 2776]
    assert rpf.numbers("§,500 4,847") == [5500, 4847]


def test_notes_before_the_values_are_not_the_values():
    """Provisions for liabilities 19,20 (6,676) (9,478)."""
    assert rpf._values("Provisions for liabilities 19,20 (6,676) (9,478)")[1] == [-6676, -9478]


def test_a_dash_in_the_values_is_a_nil():
    assert rpf.numbers("- 1,467,000") == [0, 1467000]


# ── the identities ─────────────────────────────────────────────────────────

def test_two_misread_figures_are_corrected_to_the_only_balance_sheet_that_adds_up():
    levels = rpf.read_text(GLOUCESTER, 2025)["levels"]
    read = levels["plain"]
    assert read["fields"]["creditors_within_year"] == 1_977_723
    assert read["fields"]["total_assets_less_current_liabilities"] == -1_467_441
    assert read["fields"]["net_assets"] == -1_467_441
    assert sorted(read["fixes"]) == ["CL", "TALCL"]


def test_a_subtotal_on_the_wrong_line_is_placed_by_the_identities():
    read = rpf.read_text(WEST_HAM, 2025)["levels"]["plain"]
    f = read["fields"]
    assert f["fixed_assets"] == 258_616_000 and f["current_assets"] == 37_455_000
    assert f["net_assets"] == -216_622_000
    assert f["creditors_after_year"] == 90_821_000
    assert read["fixes"] == []


def test_the_items_under_a_heading_are_kept_only_if_they_make_its_total():
    f = rpf.read_text(WEST_HAM, 2025)["levels"]["plain"]["fields"]
    assert f["intangible_assets"] == 223_152_000 and f["tangible_assets"] == 35_464_000
    assert f["share_capital"] == 5_500_000


def test_a_correction_more_than_one_character_away_is_not_made():
    """A figure OCR got badly wrong is a reading refused, not a reading fixed."""
    broken = WEST_HAM.replace("(377,741)", "(312,000)")
    result = rpf.read_text(broken, 2025)
    assert "plain" not in result["levels"]
    assert any("does not balance" in r for r in result["rejected"])


def test_a_balance_sheet_for_another_year_is_not_taken():
    result = rpf.read_text(WEST_HAM, 2024)
    assert not result["levels"]
    assert any("not 2024" in r for r in result["rejected"])


def test_the_narrative_is_never_read_as_a_balance_sheet():
    text = ("As at 30 June 2025, the company had net current liabilities of £153,623,451.\n"
            "The directors consider the company a going concern.\n")
    assert rpf.blocks(text) == []


def test_two_readings_that_both_add_up_are_refused():
    """
    Equal candidates that the identities cannot separate: no figure is
    output, because either could be the misread one.
    """
    cands = {"CA": [100, 200], "CL": [50, 150], "NCA": [50], "FA": [0], "TALCL": [50], "EQ": [50]}
    assert rpf.solve(cands)["ok"] is False


def test_only_figures_an_identity_checked_are_output():
    cands = {"CA": [731763, 5], "NCA": [-230815], "TALCL": [-230815], "FA": [0],
             "NA": [-230815], "EQ": [-230815]}
    result = rpf.solve(cands)
    assert result["ok"] and "CA" not in result["values"]


# ── the notes ──────────────────────────────────────────────────────────────

ARSENAL_NOTES = """The average monthly number of persons employed by the Group during the year was:
2025 2024
Number Number
Playing staff 101 117
Training staff 90 84
Commercial and Administrative staff 564 513
Ground staff 116 112
871 826
In addition, the Group used on average 1,462 temporary staff each month.
2025 2024
£000 £7000
Staff costs:
Wages and salaries 303,171 286,960
Social security costs 40,412 38,021
Other pension costs 3,221 2,841
346,804 327,822
"""


def test_headcount_is_the_total_its_categories_make():
    assert rpf.read_notes(ARSENAL_NOTES)["employees"] == 871


def test_staff_costs_take_the_unit_printed_above_the_table():
    assert rpf.read_notes(ARSENAL_NOTES)["staff_costs"] == 346_804_000


def test_a_table_whose_items_miss_its_total_is_not_read():
    broken = ARSENAL_NOTES.replace("871 826", "900 826")
    assert "employees" not in rpf.read_notes(broken)


# ── into the rows ──────────────────────────────────────────────────────────

def _readings(level="plain", fields=None, doc=None):
    return {"DOC": {"club_id": "giant-fc", "made_up_date": "2025-06-30",
                    "levels": {level: {"fields": fields or {"net_assets": -1_467_441,
                                                             "employees": 14},
                                       "fixes": {"CL"}, "from_contents": False}},
                    "doc": doc or {"_disclosure": "small_company"}}}


def test_a_scan_fills_a_club_season_nobody_else_has_and_says_how():
    rows = pca.build_rows([], [], _readings())["rows"]
    assert len(rows) == 1
    flags = json.loads(rows[0]["flags"])
    assert "pdf_ocr" in flags and "ocr_corrected" in flags
    assert rows[0]["net_assets"] == "-1467441" and rows[0]["employees"] == "14"


def test_a_machine_readable_filing_wins_over_a_scan_for_the_same_season():
    facts = [{"concept": "NetAssetsLiabilities", "kind": "num", "value": "5", "dimensions": "",
              "period_end": "2025-06-30", "period_start": "", "instant": "1", "prefix": "core",
              "unit": "GBP", "club_id": "giant-fc", "company_number": "1", "document": "X",
              "filing_date": "2026-01-01", "made_up_date": "2025-06-30"}]
    rows = pca.build_rows(facts, [], _readings())["rows"]
    assert len(rows) == 1 and rows[0]["net_assets"] == "5"
    assert "ixbrl_auto" in json.loads(rows[0]["flags"])


def test_profit_and_loss_from_a_scan_never_reaches_a_small_company_row():
    rows = pca.build_rows([], [], _readings(fields={"net_assets": 1, "staff_costs": 9}))["rows"]
    assert rows[0]["staff_costs"] == "" and rows[0]["net_assets"] == "1"


def test_a_hand_row_is_topped_up_from_a_scan_only_at_its_level():
    hand = {c: "" for c in finances.COLUMNS} | {
        "club_id": "giant-fc", "season_end_year": "2025", "disclosure": "full",
        "company_number": "", "entity_name": "", "consolidation_level": "club",
        "turnover": "900000", "flags": '["press_reported"]'}
    readings = _readings()
    readings["DOC"]["levels"]["group"] = {"fields": {"net_assets": 999}, "fixes": set(),
                                          "from_contents": False}
    readings["DOC"]["levels"]["company"] = {"fields": {"net_assets": 111}, "fixes": set(),
                                            "from_contents": False}
    # No entity on the hand row: nothing is added, whatever the level.
    out = pca.build_rows([], [hand], readings)
    assert out["rows"][0]["net_assets"] == ""
    hand["entity_name"] = "Giant FC Limited"
    entries = pca._pdf_entries(readings)
    entries[("giant-fc", 2025)]["entity_name"] = "Giant FC Limited"
    assert pca._pdf_level(readings["DOC"]["levels"], "company") == "company"
    assert pca._pdf_level(readings["DOC"]["levels"], "group") == "group"
