"""Luck: expected points from odds and from shots, and what the page reads off them."""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import luck  # noqa: E402
import match_stats  # noqa: E402
import pipeline  # noqa: E402


def test_the_margin_comes_out_in_proportion():
    p = luck.probabilities([2.0], [3.4], [3.8])
    assert p.sum() == pytest.approx(1.0)
    assert p[0, 0] > p[0, 2] > 0
    assert np.isnan(luck.probabilities([1.1], [1.1], [1.1])).all()     # a 270% book is a typo


def test_poisson_results_add_up_and_favour_the_side_with_more_shots():
    q = luck.poisson_wdl([2.0, 0.0, 1.0], [0.5, 0.0, 1.0])
    assert q.sum(axis=1) == pytest.approx([1, 1, 1])
    assert q[0, 0] > 0.6 and q[1, 1] == pytest.approx(1.0)              # no shots, no goals: a draw
    assert q[2, 0] == pytest.approx(q[2, 2])


def league(seasons=(2020, 2021, 2022), n=8, seed=3, lucky="club-0", unlucky="club-7", relegate=2):
    """
    A league whose odds are the truth. Each season the clubs play twice;
    one club is handed wins the odds did not expect, another loses draws.
    """
    rng = np.random.default_rng(seed)
    conn = sqlite3.connect(":memory:")
    conn.execute(pipeline.CREATE_STANDINGS_SQL)
    conn.execute(pipeline.CREATE_MATCHES_SQL)
    conn.execute(match_stats.CREATE_SQL)
    conn.execute("CREATE TABLE club_master (club_id TEXT PRIMARY KEY, canonical_name TEXT)")
    conn.executemany("INSERT INTO club_master VALUES (?, ?)", [(f"club-{i}", f"Club {i}") for i in range(n)])
    strength = np.linspace(1.6, 0.6, n)
    for season in seasons:
        pts = {i: 0 for i in range(n)}
        for h in range(n):
            for a in range(n):
                if h == a:
                    continue
                lh, la = strength[h] * 1.1, strength[a]
                ph, pd_, pa = luck.poisson_wdl([lh], [la])[0]
                hg, ag = rng.poisson(lh), rng.poisson(la)
                if f"club-{h}" == lucky and hg <= ag:
                    hg = ag + 1
                if f"club-{h}" == unlucky and hg >= ag:
                    ag = hg + 1
                ftr = "H" if hg > ag else "A" if ag > hg else "D"
                pts[h] += 3 if ftr == "H" else 1 if ftr == "D" else 0
                pts[a] += 3 if ftr == "A" else 1 if ftr == "D" else 0
                hs, as_ = hg + rng.poisson(2), ag + rng.poisson(2)
                conn.execute("INSERT INTO matches (season_end_year, tier, division_id, match_date, home_club_id,"
                             " away_club_id, home_name, away_name, fthg, ftag, ftr) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (season, 2, "champ", f"{season - 1}-09-01", f"club-{h}", f"club-{a}", f"Club {h}",
                              f"Club {a}", hg, ag, ftr))
                conn.execute("INSERT INTO match_stats (season_end_year, tier, division_id, home_name, away_name,"
                             " mkt_h, mkt_d, mkt_a, home_sot, away_sot) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (season, 2, "champ", f"Club {h}", f"Club {a}", 0.95 / ph, 0.95 / pd_, 0.95 / pa, hs, as_))
        table = sorted(pts, key=lambda i: -pts[i])
        for pos, i in enumerate(table, 1):
            status = "Promoted" if pos <= 2 else "Relegated" if pos > n - relegate else "Stayed"
            conn.execute("INSERT INTO standings (season_end_year, tier, division_id, club_id, club_name, position,"
                         " points, status) VALUES (?,?,?,?,?,?,?,?)",
                         (season, 2, "champ", f"club-{i}", f"Club {i}", pos, pts[i], status))
    conn.commit()
    return conn


def test_the_lucky_club_is_lucky_on_both_measures_and_the_unlucky_one_is_not():
    conn = league()
    cs = luck.club_seasons(luck.load_matches(conn))
    assert len(cs) == 24 and (cs["cov_o"] == 1).all() and (cs["cov_s"] == 1).all()
    by = cs.groupby("club_id")[["luck_o", "luck_s"]].mean()
    assert by.loc["club-0", "luck_o"] > 3 and by.loc["club-7", "luck_o"] < -3
    # Narrow wins with no edge in shots on target look lucky to the shots too.
    assert by.loc["club-0", "luck_s"] > 0 > by.loc["club-7", "luck_s"]
    # Expected points never stray from points by more than the luck.
    assert (cs["pts"] - cs["xpts_o"] - cs["luck_o"]).abs().max() < 1e-9


def test_decided_by_luck_names_the_clubs_on_both_sides_of_a_line():
    conn = league()
    cs = luck.club_seasons(luck.load_matches(conn))
    flips = luck.decided_by_luck(conn, cs)
    for f in flips:
        assert f["zone"] in {"promoted", "relegated"}
        assert (f["happened"] and f["xpos"] != f["position"]) or not f["happened"]
    # Every flip comes in pairs: one club in that should not be, one out that should not be.
    from collections import Counter
    pairs = Counter((f["season"], f["zone"], f["happened"]) for f in flips)
    for (season, zone, happened), k in pairs.items():
        assert pairs[(season, zone, not happened)] == k


def test_an_in_progress_division_is_never_called_for_luck():
    conn = league(seasons=(2027,))
    conn.execute("UPDATE standings SET status = 'In progress'")
    cs = luck.club_seasons(luck.load_matches(conn))
    assert luck.decided_by_luck(conn, cs) == []


def test_assemble_is_empty_without_odds_and_full_with_them():
    empty = sqlite3.connect(":memory:")
    empty.execute(pipeline.CREATE_MATCHES_SQL)
    assert luck.assemble(empty) == {}
    d = luck.assemble(league(seasons=tuple(range(2010, 2022))))
    assert d["newest"] == 2021 and d["first_o"] == 2010
    assert d["luckiest"][0]["club_id"] == "club-0" and d["unluckiest"][0]["club_id"] == "club-7"
    assert all(r["season"] < 2021 for r in d["luckiest"])               # the season in play is not history
    assert d["current"] and all(r["season"] == 2021 for r in d["current"])
    beaters = {b["club_id"]: b for b in d["beaters"]}
    assert beaters["club-0"]["clear"] and beaters["club-0"]["mean"] > 0
    assert d["persist_o"]["n"] > 50 and d["persist_o"]["ability"] > d["persist_o"]["luck"]
    assert len(d["scatter"]) == 12 * 8 and d["scatter"][0][5] is not None


def test_the_page_builds_with_the_scatter_data(tmp_path, monkeypatch):
    import shutil

    import site_build as sb
    from site_build import SiteBuilder
    from test_digest import _make_db

    src = league(seasons=tuple(range(2012, 2024)))
    full = _make_db()
    full.execute("ALTER TABLE matches ADD COLUMN division_id TEXT")
    full.execute(match_stats.CREATE_SQL)
    for table in ("matches", "match_stats"):
        cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
        keep = [c for c in cols if c in {r[1] for r in full.execute(f"PRAGMA table_info({table})")}]
        full.executemany(f"INSERT INTO {table} ({', '.join(keep)}) VALUES ({', '.join('?' * len(keep))})",
                         src.execute(f"SELECT {', '.join(keep)} FROM {table}").fetchall())
    for (cid, name) in src.execute("SELECT club_id, canonical_name FROM club_master"):
        full.execute("INSERT INTO club_master (club_id, canonical_name) VALUES (?, ?)", (cid, name))
    st_cols = [r[1] for r in full.execute("PRAGMA table_info(standings)")]
    keep = [c for c in ("season_end_year", "tier", "club_id", "club_name", "position", "points", "status") if c in st_cols]
    full.executemany(f"INSERT INTO standings ({', '.join(keep)}) VALUES ({', '.join('?' * len(keep))})",
                     src.execute(f"SELECT {', '.join(keep)} FROM standings").fetchall())
    full.commit()
    disk = tmp_path / "england.db"
    dst = sqlite3.connect(disk); full.backup(dst); dst.close()

    content_dir = tmp_path / "content" / "insights"
    content_dir.mkdir(parents=True)
    (content_dir / "luck.md").write_text("Some of it was luck.\n", encoding="utf-8")
    shutil.copytree(Path(__file__).parent.parent / "templates", tmp_path / "templates")
    shutil.copytree(Path(__file__).parent.parent / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "site"
    SiteBuilder(disk, out, charts_enabled=False).build()

    page = (out / "insights" / "luck" / "index.html").read_text(encoding="utf-8")
    assert "Some of it was luck." in page and 'id="luck-scatter"' in page
    for heading in ("The luckiest and unluckiest seasons", "Decided by luck", "Does luck last?",
                    "Beating the market", "When the odds and the shots disagree", "This season so far"):
        assert heading in page
    assert "Club 0" in page
    data = (out / "insights" / "luck" / "luck-data.js").read_text(encoding="utf-8")
    assert data.startswith("window.LUCK_DATA = {") and '"rows"' in data
    assert "Points against expected points" in (out / "insights" / "index.html").read_text(encoding="utf-8")


def test_the_ends_of_a_table_select_for_luck():
    conn = league(seasons=tuple(range(2010, 2022)))
    out = {o["label"]: o for o in luck.by_outcome(conn, luck.club_seasons(luck.load_matches(conn)))}
    assert out["Promoted automatically"]["mean"] > out["Stayed"]["mean"] > out["Relegated"]["mean"]
    d = luck.assemble(conn)
    assert d["decided_examined"] >= len({(f["season"], f["tier"]) for f in d["decided"]})
