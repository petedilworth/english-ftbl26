"""
Reading figures out of iXBRL filings.

The risk here is the mirror of the mapping's: not a wrong company, but a
wrong number attached to the right one. A figure is either read from the
tag that says what it is, or it is not read at all and the file is named
so the missing spelling can be added. There is no third path where the
parser takes the nearest number on the page.
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import finances                                          # noqa: E402
import parse_club_accounts as pca                        # noqa: E402


def ixbrl(facts, contexts=None):
    """A minimal filing in the shape Companies House actually serves."""
    contexts = contexts or [
        ('<xbrli:context id="cur"><xbrli:period>'
         '<xbrli:startDate>2023-07-01</xbrli:startDate>'
         '<xbrli:endDate>2024-06-30</xbrli:endDate></xbrli:period></xbrli:context>'),
        ('<xbrli:context id="prior"><xbrli:period>'
         '<xbrli:startDate>2022-07-01</xbrli:startDate>'
         '<xbrli:endDate>2023-06-30</xbrli:endDate></xbrli:period></xbrli:context>'),
    ]
    return (
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
        'xmlns:xbrli="http://www.xbrl.org/2003/instance">'
        "<body><div style=\"display:none\">" + "".join(contexts) + "</div>"
        + "".join(facts) + "</body></html>"
    ).encode()


def fact(name, value, context="cur", **attrs):
    extra = "".join(f' {k}="{v}"' for k, v in attrs.items())
    return (f'<ix:nonFraction name="{name}" contextRef="{context}" '
            f'unitRef="GBP"{extra}>{value}</ix:nonFraction>')


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    return path


# ── reading one number correctly ───────────────────────────────────────────

def test_a_tagged_turnover_is_read(tmp_path):
    path = write(tmp_path, "a__1.xhtml", ixbrl([fact("core:TurnoverRevenue", "1,234,567")]))
    result = pca.read_document(path)
    assert result["ok"]
    assert result["fields"]["turnover"] == 1234567
    assert result["disclosure"] == finances.DISCLOSURE_FULL
    assert result["period_end"] == "2024-06-30"


def test_the_scale_attribute_is_not_decoration(tmp_path):
    """
    scale="3" means the figure on the page is in thousands. Ignoring it
    understates a Premier League turnover by a factor of a thousand, and
    nothing about the rendered number says so.
    """
    path = write(tmp_path, "a__1.xhtml",
                 ixbrl([fact("core:TurnoverRevenue", "616,600", scale="3")]))
    assert pca.read_document(path)["fields"]["turnover"] == 616_600_000


@pytest.mark.parametrize("markup,expected", [
    (fact("core:ProfitLossOnOrdinaryActivitiesBeforeTax", "17,700", sign="-"), -17700),
    (fact("core:ProfitLossOnOrdinaryActivitiesBeforeTax", "(17,700)"), -17700),
    (fact("core:ProfitLossOnOrdinaryActivitiesBeforeTax", "17,700"), 17700),
])
def test_a_loss_is_read_as_a_loss(tmp_path, markup, expected):
    """
    Both spellings are used: sign="-" as an attribute, and brackets in
    the text. A loss read as a profit is the most consequential single
    error this parser could make.
    """
    path = write(tmp_path, "a__1.xhtml", ixbrl([markup]))
    assert pca.read_document(path)["fields"]["profit_before_tax"] == expected


def test_the_current_year_wins_over_the_comparative(tmp_path):
    """Accounts print last year beside this year, tagged identically."""
    path = write(tmp_path, "a__1.xhtml", ixbrl([
        fact("core:TurnoverRevenue", "100", context="prior"),
        fact("core:TurnoverRevenue", "200", context="cur"),
    ]))
    result = pca.read_document(path)
    assert result["fields"]["turnover"] == 200
    assert result["period_end"] == "2024-06-30"


def test_an_alternative_tag_spelling_is_accepted(tmp_path):
    """The FRC taxonomies renamed these; filings in the wild use both."""
    path = write(tmp_path, "a__1.xhtml",
                 ixbrl([fact("uk-gaap:TurnoverGrossOperatingRevenue", "500")]))
    assert pca.read_document(path)["fields"]["turnover"] == 500


# ── saying what it could not read ──────────────────────────────────────────

def test_a_filing_with_no_turnover_is_a_small_company_not_a_gap(tmp_path):
    """
    The small-company regime permits a balance sheet and no
    profit-and-loss. That is a finding about the club, and the site
    already renders it as one.
    """
    path = write(tmp_path, "a__1.xhtml", ixbrl([fact("core:NetAssetsLiabilities", "42,000")]))
    result = pca.read_document(path)
    assert result["ok"]
    assert result["disclosure"] == finances.DISCLOSURE_SMALL_COMPANY


def test_an_untagged_document_is_reported_not_guessed_at(tmp_path):
    path = write(tmp_path, "a__1.xhtml",
                 b'<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                 b"<p>Turnover 1,234,567</p></body></html>")
    result = pca.read_document(path)
    assert not result["ok"]
    assert "no iXBRL tags" in result["reason"]


def test_an_unparseable_document_does_not_stop_the_run(tmp_path):
    path = write(tmp_path, "a__1.xhtml", b"%PDF-1.4 not xml at all")
    result = pca.read_document(path)
    assert not result["ok"]
    assert "not parseable" in result["reason"]


def test_an_unknown_spelling_is_named_with_what_it_did_see(tmp_path):
    """
    The parser is designed to be shown what it could not read: the
    concepts it found are what say which spelling to add.
    """
    path = write(tmp_path, "a__1.xhtml",
                 ixbrl([fact("core:SomeUnknownRevenueConcept", "900")]))
    result = pca.read_document(path)
    assert not result["ok"]
    assert "SomeUnknownRevenueConcept" in result["concepts"]


# ── the season, and what must never be overwritten ─────────────────────────

@pytest.mark.parametrize("end,season", [
    ("2024-06-30", 2024), ("2024-05-31", 2024), ("2024-12-31", 2024), (None, None),
])
def test_the_season_is_the_year_the_period_ends(end, season):
    """Matching what the hand-collected rows already do."""
    assert pca._season(end) == season


def test_a_figure_is_never_carried_on_a_row_that_disclosed_nothing(tmp_path):
    """
    finances.seed_club_finances refuses this, and it is right to: a club
    filing under the small-company regime cannot also have a turnover.
    """
    path = write(tmp_path, "a__1.xhtml", ixbrl([
        fact("core:NetAssetsLiabilities", "42,000"),
        fact("core:StaffCostsEmployeeBenefitsExpense", "9,000"),
    ]))
    result = pca.read_document(path)
    assert result["disclosure"] == finances.DISCLOSURE_SMALL_COMPANY
    assert "turnover" not in result["fields"]


def test_every_column_it_writes_is_one_the_loader_knows():
    """The row is built from finances.COLUMNS, so it cannot drift."""
    assert "flags" in finances.COLUMNS and "disclosure" in finances.COLUMNS
    for field in ("turnover", "staff_costs", "profit_before_tax"):
        assert field in finances.COLUMNS


def test_hand_collected_rows_are_what_existing_rows_reports():
    """
    The guard against replacing a researched row with a machine-read one
    is this set, so it has to actually be populated.
    """
    rows = pca.existing_rows()
    assert rows, "club_finances.csv should already hold hand-collected rows"
    assert all(isinstance(season, int) for _club, season in rows)
