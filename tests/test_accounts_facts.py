"""
Every fact in a filing, and the balance sheet read out of them.

Three promises are pinned here. Nothing in a filing is dropped on the way
to the facts file. A small-company filing's balance sheet reaches the
data, where before every figure on such a row was refused. And a row a
person collected is never changed except to gain a column that did not
exist when they wrote it, from a filing by the entity they named.
"""
import csv
import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import finances                                          # noqa: E402
import parse_club_accounts as pca                        # noqa: E402

NS = ('xmlns="http://www.w3.org/1999/xhtml" '
      'xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
      'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
      'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')

CONTEXTS = (
    '<xbrli:context id="y"><xbrli:period><xbrli:startDate>2024-07-01</xbrli:startDate>'
    '<xbrli:endDate>2025-06-30</xbrli:endDate></xbrli:period></xbrli:context>'
    '<xbrli:context id="b"><xbrli:period><xbrli:instant>2025-06-30</xbrli:instant>'
    '</xbrli:period></xbrli:context>'
    '<xbrli:context id="b-within"><xbrli:entity><xbrli:segment>'
    '<xbrldi:explicitMember dimension="core:MaturitiesOrExpirationPeriodsDimension">'
    'core:WithinOneYear</xbrldi:explicitMember></xbrli:segment></xbrli:entity>'
    '<xbrli:period><xbrli:instant>2025-06-30</xbrli:instant></xbrli:period></xbrli:context>'
    '<xbrli:context id="b-after"><xbrli:entity><xbrli:segment>'
    '<xbrldi:explicitMember dimension="core:MaturitiesOrExpirationPeriodsDimension">'
    'core:AfterOneYear</xbrldi:explicitMember></xbrli:segment></xbrli:entity>'
    '<xbrli:period><xbrli:instant>2025-06-30</xbrli:instant></xbrli:period></xbrli:context>'
    '<xbrli:context id="b-shares"><xbrli:entity><xbrli:segment>'
    '<xbrldi:explicitMember dimension="core:EquityClassesDimension">'
    'core:ShareCapital</xbrldi:explicitMember></xbrli:segment></xbrli:entity>'
    '<xbrli:period><xbrli:instant>2025-06-30</xbrli:instant></xbrli:period></xbrli:context>'
    '<xbrli:unit id="GBP"><xbrli:measure>iso4217:GBP</xbrli:measure></xbrli:unit>'
    '<xbrli:unit id="pure"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>'
)


def doc(body: str) -> bytes:
    return (f"<html {NS}><body><div style=\"display:none\"><ix:header><ix:resources>"
            f"{CONTEXTS}</ix:resources></ix:header></div>{body}</body></html>").encode()


def num(name, value, ctx="b", unit="GBP", **attrs):
    extra = "".join(f' {k}="{v}"' for k, v in attrs.items())
    return (f'<ix:nonFraction name="{name}" contextRef="{ctx}" unitRef="{unit}"{extra}>'
            f"{value}</ix:nonFraction>")


def text(name, value, ctx="y"):
    return f'<ix:nonNumeric name="{name}" contextRef="{ctx}">{value}</ix:nonNumeric>'


SMALL_CLUB = doc(
    text("bus:EntityCurrentLegalOrRegisteredName", "Marine Association Football Club Limited")
    + num("core:AverageNumberEmployeesDuringPeriod", "23", ctx="y", unit="pure")
    + num("core:FixedAssets", "410,000")
    + num("core:CurrentAssets", "52,500")
    + num("core:CashBankOnHand", "31,200")
    + num("core:Creditors", "88,000", ctx="b-within")
    + num("core:Creditors", "120,000", ctx="b-after")
    + num("core:NetAssetsLiabilities", "254,500")
    + num("core:Equity", "100", ctx="b-shares")
    + num("core:NetAssetsLiabilities", "254,500")          # tagged twice: in a note too
)


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    return path


# ── facts ──────────────────────────────────────────────────────────────────

def test_every_fact_keeps_its_period_dimensions_and_unit(tmp_path):
    facts = pca.extract(write(tmp_path, "marine-fc__1.xhtml", SMALL_CLUB))["facts"]
    within = [f for f in facts if f["concept"] == "Creditors" and "WithinOneYear" in f["dimensions"]]
    assert within and within[0]["value"] == "88000"
    assert within[0]["instant"] == "1" and within[0]["period_end"] == "2025-06-30"
    assert within[0]["dimensions"] == "MaturitiesOrExpirationPeriodsDimension=WithinOneYear"
    staff = [f for f in facts if f["concept"] == "AverageNumberEmployeesDuringPeriod"][0]
    assert staff["unit"] == "pure" and staff["period_start"] == "2024-07-01"


def test_a_figure_tagged_twice_is_one_fact(tmp_path):
    facts = pca.extract(write(tmp_path, "m__1.xhtml", SMALL_CLUB))["facts"]
    assert sum(1 for f in facts if f["concept"] == "NetAssetsLiabilities") == 1


def test_a_dash_formatted_as_zero_is_zero_not_blank(tmp_path):
    """
    ixt:zerodash renders a nil balance as a dash. Read as blank, a club
    with no long-term debt looks like a club that did not say.
    """
    body = num("core:Creditors", "-", ctx="b-after", format="ixt:zerodash")
    facts = pca.extract(write(tmp_path, "m__1.xhtml", doc(body)))["facts"]
    assert [f["value"] for f in facts if f["concept"] == "Creditors"] == ["0"]


def test_a_nil_fact_is_not_a_zero(tmp_path):
    body = num("core:Creditors", "", ctx="b-after", **{"xsi:nil": "true"})
    facts = pca.extract(write(tmp_path, "m__1.xhtml", doc(body)))["facts"]
    assert not [f for f in facts if f["concept"] == "Creditors"]


def test_a_long_text_fact_is_capped_not_dropped(tmp_path):
    body = text("core:DescriptionAccountingPolicies", "x" * 5000)
    facts = pca.extract(write(tmp_path, "m__1.xhtml", doc(body)))["facts"]
    policy = [f for f in facts if f["concept"] == "DescriptionAccountingPolicies"][0]
    assert len(policy["value"]) == pca.TEXT_CAP and policy["value"].endswith("…")


@pytest.mark.parametrize("sentence,flagged", [
    ("Material uncertainty related to going concern. We draw attention to note 2, which "
     "indicates that a material uncertainty exists that may cast significant doubt.", True),
    ("Based on the work we have performed, we have not identified any material uncertainty "
     "relating to going concern.", False),
    ("We have not identified any material uncertainties relating to events or conditions "
     "that may cast significant doubt on the company's ability to continue as a going "
     "concern.", False),
])
def test_a_going_concern_warning_is_read_and_its_negation_is_not(tmp_path, sentence, flagged):
    """
    Every clean audit report contains the words "material uncertainty"
    and "going concern", negated. Flagging those would put a warning on
    every audited club in the country.
    """
    body = num("core:NetAssetsLiabilities", "1") + f"<p>{sentence}</p>"
    facts = pca.extract(write(tmp_path, "m__1.xhtml", doc(body)))["facts"]
    gc = [f["value"] for f in facts if f["concept"] == pca.GOING_CONCERN][0]
    assert (gc != "none found") == flagged


def test_facts_from_a_filing_no_longer_fetched_are_kept(tmp_path):
    """
    Each new year's accounts push the oldest filing out of the fetch's
    two-filing window. What was read from it is still true.
    """
    docs = tmp_path / "docs"; docs.mkdir()
    facts = tmp_path / "facts"
    pca.write_facts([{c: "" for c in pca.FACT_COLUMNS} | {
        "club_id": "marine-fc", "document": "OLD", "concept": "NetAssetsLiabilities",
        "kind": "num", "value": "1"}], facts)
    write(docs, "marine-fc__1.xhtml", SMALL_CLUB)
    pca.cmd_facts(docs, facts)
    kept = {r["document"] for r in pca.read_facts(facts)}
    assert "OLD" in kept and "marine-fc__1" in kept


def test_the_facts_file_is_byte_identical_when_nothing_changed(tmp_path):
    docs = tmp_path / "docs"; docs.mkdir()
    write(docs, "marine-fc__1.xhtml", SMALL_CLUB)
    facts = tmp_path / "facts"
    pca.cmd_facts(docs, facts)
    first = (facts / "marine-fc.tsv").read_bytes()
    pca.cmd_facts(docs, facts)
    assert (facts / "marine-fc.tsv").read_bytes() == first
    assert [p.name for p in facts.iterdir()] == ["marine-fc.tsv"]


def test_the_filing_history_names_each_document(tmp_path):
    (tmp_path / "marine-fc__filings.json").write_text(json.dumps({"items": [
        {"date": "2026-03-01", "type": "AA", "paper_filed": True,
         "description_values": {"made_up_date": "2025-06-30"},
         "links": {"document_metadata": "https://document-api/document/ABC123"}}]}))
    meta = pca.document_meta(tmp_path, tmp_path / "marine-fc__1.pdf")
    assert meta["document"] == "ABC123"
    assert meta["made_up_date"] == "2025-06-30" and meta["paper_filed"] == "yes"


# ── the balance sheet ──────────────────────────────────────────────────────

def test_a_small_company_balance_sheet_is_read_in_full(tmp_path):
    result = pca.read_document(write(tmp_path, "m__1.xhtml", SMALL_CLUB))
    f = result["fields"]
    assert result["disclosure"] == finances.DISCLOSURE_SMALL_COMPANY
    assert f["employees"] == 23
    assert f["net_assets"] == 254500 and f["cash"] == 31200
    assert f["creditors_within_year"] == 88000
    assert f["creditors_after_year"] == 120000
    assert f["share_capital"] == 100
    assert result["entity_name"].startswith("Marine")


def test_net_assets_is_never_read_from_a_slice_of_equity(tmp_path):
    """
    core:Equity tagged with a share-capital member is the share capital,
    not the club's net worth. Taking it would put £100 where £254,500
    belongs.
    """
    body = num("core:Equity", "100", ctx="b-shares")
    result = pca.read_document(write(tmp_path, "m__1.xhtml", doc(body)))
    assert "net_assets" not in result["fields"]
    assert result["fields"]["share_capital"] == 100


def test_the_period_comes_from_the_filing_history_where_it_says(tmp_path):
    facts = pca.extract(write(tmp_path, "m__1.xhtml", SMALL_CLUB))["facts"]
    assert pca.derive(facts, "2025-06-30")["fields"]["net_assets"] == 254500
    # The year before has no balance sheet in this filing, so nothing is
    # read rather than this year's figures being filed under it.
    assert pca.derive(facts, "2024-06-30")["ok"] is False


# ── the loader ─────────────────────────────────────────────────────────────

def _row(**values):
    row = {c: None for c in finances.COLUMNS}
    row.update(club_id="marine-fc", season_end_year=2025, flags=None)
    row.update(values)
    return row


def test_a_small_company_row_may_carry_its_balance_sheet():
    assert not finances._validate(_row(disclosure="small_company", net_assets=1, employees=9), set())


def test_a_small_company_row_still_may_not_carry_a_turnover():
    problems = finances._validate(_row(disclosure="small_company", turnover=1), set())
    assert problems and "turnover" in problems[0]


def test_a_club_that_did_not_file_carries_no_figures_at_all():
    problems = finances._validate(_row(disclosure="not_filed", net_assets=1), set())
    assert problems and "net_assets" in problems[0]


def test_an_old_database_gains_the_new_columns(tmp_path):
    """england.db is committed: its table predates the balance sheet."""
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.execute("CREATE TABLE club_finances (club_id TEXT NOT NULL, season_end_year INT NOT NULL,"
                 " disclosure TEXT NOT NULL, PRIMARY KEY (club_id, season_end_year))")
    conn.execute("CREATE TABLE club_master (club_id TEXT)")
    csv_path = tmp_path / "f.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, finances.COLUMNS); w.writeheader()
        w.writerow({c: "" for c in finances.COLUMNS} | {
            "club_id": "marine-fc", "season_end_year": "2025",
            "disclosure": "small_company", "net_assets": "254500", "employees": "23"})
    assert finances.seed_club_finances(conn, csv_path) == 1
    assert conn.execute("SELECT net_assets, employees FROM club_finances").fetchone() == (254500, 23)


# ── hand rows ──────────────────────────────────────────────────────────────

def _facts(tmp_path, body=SMALL_CLUB, club="marine-fc", company="00123456"):
    facts = pca.extract(write(tmp_path, f"{club}__1.xhtml", body))["facts"]
    for f in facts:
        f.update(club_id=club, company_number=company, document=f"{club}-doc",
                 filing_date="2026-03-01", made_up_date="2025-06-30")
    return facts


def _hand(**values):
    row = {c: "" for c in finances.COLUMNS}
    row.update(club_id="marine-fc", season_end_year="2025", disclosure="full",
               entity_name="Marine Association Football Club Limited",
               turnover="900000", flags='["press_reported"]')
    row.update(values)
    return row


def test_a_hand_row_gains_only_columns_that_did_not_exist_and_only_where_blank(tmp_path):
    hand = _hand(net_assets="999")                          # a person filled this
    out = pca.build_rows(_facts(tmp_path), [hand])["rows"][0]
    assert out["turnover"] == "900000"                      # untouched
    assert out["net_assets"] == "999"                       # not overwritten
    assert out["employees"] == "23"                         # filled: it was blank and new
    assert "ixbrl_balance_sheet" in json.loads(out["flags"])
    assert "press_reported" in json.loads(out["flags"])


def test_a_hand_row_naming_a_different_entity_is_left_alone(tmp_path):
    """
    A holding company and the club company under it report different
    money. Topping up a holding company's row from the club company's
    balance sheet would make one row describe two companies.
    """
    hand = _hand(entity_name="Marine Holdings Group Limited")
    result = pca.build_rows(_facts(tmp_path), [hand])
    assert result["rows"][0]["employees"] == ""
    assert result["mismatched"]


def test_a_machine_row_is_rebuilt_so_new_fields_reach_it(tmp_path):
    """
    The first version wrote turnover-only rows and skipped every
    club-season already written, so those rows could never gain a field.
    """
    old = {c: "" for c in finances.COLUMNS} | {
        "club_id": "marine-fc", "season_end_year": "2025",
        "disclosure": "small_company", "flags": '["ixbrl_auto"]'}
    out = pca.build_rows(_facts(tmp_path), [old])["rows"]
    assert len(out) == 1
    assert out[0]["net_assets"] == "254500" and out[0]["employees"] == "23"
    assert json.loads(out[0]["flags"]) == ["ixbrl_auto"]


def test_profit_and_loss_figures_never_reach_a_small_company_row(tmp_path):
    body = SMALL_CLUB.replace(b"</body>", num("core:OperatingProfitLoss", "5,000", ctx="y").encode()
                              + b"</body>")
    out = pca.build_rows(_facts(tmp_path, body), [])["rows"][0]
    assert out["disclosure"] == "small_company"
    assert out["operating_profit"] == ""
    assert out["net_assets"] == "254500"
    assert not finances._validate({c: (int(out[c]) if out[c] and c in finances.MONEY_COLUMNS
                                       else (out[c] or None)) for c in finances.COLUMNS}, set())
