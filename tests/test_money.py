"""The Money page: what it compares, what it withholds, and the page itself."""

import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import finances  # noqa: E402
import money  # noqa: E402


def _db(rows, standings):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_master (club_id TEXT, canonical_name TEXT)")
    conn.execute("CREATE TABLE standings (season_end_year INT, tier INT, division_name TEXT, club_id TEXT,"
                 " points INT, points_deducted INT, played INT)")
    conn.execute(finances.CREATE_CLUB_FINANCES_SQL)
    for club_id, season, tier, points, deducted in standings:
        conn.execute("INSERT INTO standings VALUES (?, ?, ?, ?, ?, ?, 46)",
                     (season, tier, f"Tier {tier}", club_id, points, deducted))
        conn.execute("INSERT OR IGNORE INTO club_master VALUES (?, ?)", (club_id, club_id.replace("-", " ").title()))
    for r in rows:
        r = dict({"disclosure": "full", "flags": "[]"}, **r)
        conn.execute(f"INSERT INTO club_finances ({', '.join(r)}) VALUES ({', '.join('?' * len(r))})",
                     list(r.values()))
    return conn


def _assemble(conn, tmp_path, registered=()):
    filings = tmp_path / "filings.tsv"
    filings.write_text("club_id\tcompany_number\n" + "".join(f"{c}\t0000000{i}\n" for i, c in enumerate(registered)))
    return money.assemble(conn, filings, tmp_path / "none.json")


def test_money_reads_the_way_the_page_prints_it():
    assert money.money(222_000_000) == "£222m"
    assert money.money(30_400_000) == "£30.4m"
    assert money.money(-284_000) == "−£284k"
    assert money.money(1) == "£1"
    assert money.money(None) == "–"


def test_a_balance_sheet_that_does_not_balance_is_withheld_whole(tmp_path):
    conn = _db([{"club_id": "a-fc", "season_end_year": 2025, "disclosure": "small_company", "net_assets": 5,
                 "cash": 9, "employees": 12, "flags": json.dumps(["ixbrl_auto", "does_not_balance"])}],
               [("a-fc", 2025, 6, 60, 0)])
    row = _assemble(conn, tmp_path)["latest"]["a-fc"]
    assert row["net_assets"] is None and row["cash"] is None
    assert row["employees"] == 12          # the headcount is a note, not the balance sheet


def test_a_corrected_figure_is_marked():
    row = money._prepare({"flags": json.dumps(["pdf_ocr", "ocr_corrected"]), "turnover": None,
                          "staff_costs": None}, {"tier": 7}, "X")
    assert row["doubts"] == [money.DOUBT_LABELS["ocr_corrected"]]


def test_cost_per_point_counts_the_points_won_before_any_deduction(tmp_path):
    conn = _db([{"club_id": "a-fc", "season_end_year": 2025, "staff_costs": 50_000_000, "turnover": 60_000_000},
                {"club_id": "b-fc", "season_end_year": 2025, "staff_costs": 3_000_000, "turnover": 4_000_000}],
               [("a-fc", 2025, 2, 40, 10), ("b-fc", 2025, 4, 50, 0)])
    d = _assemble(conn, tmp_path)
    assert [r["club_id"] for r in d["cost"]] == ["a-fc"]          # tiers 1-3 only
    assert d["cost"][0]["points"] == 50 and d["cost"][0]["per_point"] == 1_000_000


def test_two_years_compare_only_as_the_same_company_at_the_same_level(tmp_path):
    base = {"club_id": "a-fc", "company_number": "01", "consolidation_level": "group"}
    conn = _db([dict(base, season_end_year=2024, net_assets=10_000_000, turnover=100, staff_costs=50),
                dict(base, season_end_year=2025, net_assets=-5_000_000, turnover=100, staff_costs=90),
                dict(base, club_id="b-fc", season_end_year=2024, net_assets=1),
                dict(base, club_id="b-fc", season_end_year=2025, net_assets=2, consolidation_level="club")],
               [("a-fc", 2024, 1, 50, 0), ("a-fc", 2025, 2, 50, 0), ("b-fc", 2024, 3, 50, 0), ("b-fc", 2025, 3, 50, 0)])
    d = _assemble(conn, tmp_path)
    assert [(m["club_id"], m["change"]) for m in d["asset_moves"]] == [("a-fc", -15_000_000)]
    assert round(d["ratio_moves"][0]["change"], 2) == 0.4
    assert (d["asset_moves"][0]["tier_before"], d["asset_moves"][0]["tier"]) == (1, 2)


def test_every_club_in_the_pyramid_is_counted_by_what_it_discloses(tmp_path):
    conn = _db([{"club_id": "full-fc", "season_end_year": 2025, "turnover": 5},
                {"club_id": "s444-fc", "season_end_year": 2025, "disclosure": "small_company", "net_assets": 1,
                 "pnl_withheld": "yes"},
                {"club_id": "small-fc", "season_end_year": 2025, "disclosure": "small_company", "net_assets": 1},
                {"club_id": "late-fc", "season_end_year": 2025, "disclosure": "not_filed"}],
               [(c, 2026, 5, 0, 0) for c in ("full-fc", "s444-fc", "small-fc", "late-fc", "paper-fc", "society-fc")])
    d = _assemble(conn, tmp_path, registered=["paper-fc"])
    assert d["disclosure"][5] == {"full": 1, "withheld": 1, "small": 1, "unread": 2, "unmatched": 1}


def test_the_cliff_names_a_median_on_too_few_filings_rather_than_drawing_it(tmp_path):
    conn = _db([{"club_id": f"c{i}", "season_end_year": 2025, "turnover": 10 * i, "net_assets": i}
                for i in range(1, 3)],
               [(f"c{i}", 2025, 1, 50, 0) for i in range(1, 3)])
    d = _assemble(conn, tmp_path)
    assert d["cliff"][0]["turnover_n"] == 2


def test_a_database_without_the_finances_table_gives_nothing(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE standings (season_end_year INT)")
    assert money.assemble(conn, tmp_path / "f.tsv", tmp_path / "c.json") == {}


def test_the_page_builds(tmp_path, monkeypatch):
    import site_build as sb
    from site_build import SiteBuilder
    from test_digest import _make_db

    full = _make_db()
    full.execute(finances.CREATE_CLUB_FINANCES_SQL)
    for club, na in (("giant-fc", -2_000_000), ("steady-fc", 3_000_000)):
        for season, wages in ((2024, 8_000_000), (2025, 9_000_000)):
            full.execute("INSERT INTO club_finances (club_id, season_end_year, company_number, disclosure,"
                         " turnover, staff_costs, net_assets, flags) VALUES (?, ?, ?, 'full', ?, ?, ?, '[]')",
                         (club, season, club[:4], 10_000_000, wages, na + season))
    full.commit()          # an open transaction would hold the backup below forever
    disk = tmp_path / "england.db"
    dst = sqlite3.connect(disk); full.backup(dst); dst.close()
    content_dir = tmp_path / "content" / "insights"
    content_dir.mkdir(parents=True)
    (content_dir / "money.md").write_text("Follow the money.\n", encoding="utf-8")
    shutil.copytree(Path(__file__).parent.parent / "templates", tmp_path / "templates")
    shutil.copytree(Path(__file__).parent.parent / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "site"
    SiteBuilder(disk, out, charts_enabled=False).build()

    page = (out / "insights" / "money" / "index.html").read_text(encoding="utf-8")
    assert "Follow the money." in page
    for heading in ("The cliff between tiers", "Cost per point", "Biggest movers", "What each club discloses",
                    "The money league"):
        assert heading in page
    assert "£9.0m" in page and "−£2.0m" in page
    assert "insights/money/index.html" in (out / "insights" / "index.html").read_text(encoding="utf-8")
