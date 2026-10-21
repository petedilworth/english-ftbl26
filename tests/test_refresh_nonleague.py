"""The daily non-league refresh: what it fetches, what it writes, and what it refuses."""

import datetime
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import entities  # noqa: E402
import refresh_nonleague as rn  # noqa: E402

SEASON = 2027
CLUBS = {"ALF": "Alfreton Town", "BAN": "Banbury United", "BIS": "Bishop's Stortford", "BRA": "Brackley Town"}


def _article(matches: dict[tuple[str, str], str], clubs: dict[str, str] = CLUBS,
             heading: str = "National League North") -> str:
    names = "\n".join(f"|name_{c}=[[{n} F.C.|{n}]]" for c, n in clubs.items())
    scores = "\n".join(f"|match_{h}_{a}={s}" for (h, a), s in matches.items())
    return (f"== {heading} ==\n=== League table ===\n{{{{Fb cl header}}}}\n|name_ALF=[[Decoy]]\n"
            f"=== Results ===\n{{{{Sports results\n|team_order={', '.join(clubs)}\n{names}\n{scores}\n}}}}\n"
            f"== National League South ==\n=== Results ===\n{{{{Sports results\n|team_order=X, Y\n"
            f"|name_X=Xton\n|name_Y=Yville\n|match_X_Y=1–0\n}}}}\n")


def _resolver(names=CLUBS.values()):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_master (club_id TEXT, canonical_name TEXT, name_variants TEXT)")
    conn.executemany("INSERT INTO club_master VALUES (?,?,?)",
                     [(n.lower().replace(" ", "-").replace("'", ""), n, "[]") for n in names])
    return entities.build_resolver(conn)


FIRST = {("ALF", "BAN"): "2–0", ("ALF", "BIS"): "3-0", ("BAN", "ALF"): "1—1", ("BIS", "BRA"): "0−2"}


def test_grids_parse_the_season_from_the_articles_and_only_that_season():
    found = rn.grids(SEASON, {"National_League": _article(FIRST)})
    assert set(found) == {"national-league-north", "national-league-south"}
    g = found["national-league-north"]
    assert g["codes"] == ["ALF", "BAN", "BIS", "BRA"] and g["names"]["BIS"] == "Bishop's Stortford"
    assert len(g["rows"]) == 4, "every dash the articles use counts as a score"


def test_writes_a_fresh_grid_then_only_a_grown_one(tmp_path):
    rn.MIN_CLUBS, keep = 4, rn.MIN_CLUBS
    try:
        resolver = _resolver()
        report = rn.refresh(SEASON, {"National_League": _article(FIRST)}, resolver, tmp_path)
        assert report["national-league-north"] == "written, 4 matches (+4)"
        assert report["national-league-south"].startswith("refused: club name(s) this project cannot resolve: Xton, Yville")
        assert report["isthmian-league-premier"] == "no grid in the article"
        path = tmp_path / "2627_national-league-north_nl.csv"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR"
        assert lines[1] == "national-league-north,,Alfreton Town,Banbury United,2,0,H"
        assert "national-league-north,,Bishop's Stortford,Brackley Town,0,2,A" in lines

        # The same grid again: nothing to write.
        report = rn.refresh(SEASON, {"National_League": _article(FIRST)}, resolver, tmp_path)
        assert report["national-league-north"] == "unchanged, 4 matches"

        # A grown grid is written; a dry run says so and leaves the file alone.
        more = {**FIRST, ("BRA", "ALF"): "2–2"}
        before = path.read_text(encoding="utf-8")
        assert rn.refresh(SEASON, {"National_League": _article(more)}, resolver, tmp_path, dry_run=True)[
            "national-league-north"] == "would write, 5 matches (+1)"
        assert path.read_text(encoding="utf-8") == before
        assert rn.refresh(SEASON, {"National_League": _article(more)}, resolver, tmp_path)[
            "national-league-north"] == "written, 5 matches (+1)"
        assert len(path.read_text(encoding="utf-8").splitlines()) == 6
    finally:
        rn.MIN_CLUBS = keep


def test_refuses_a_grid_that_went_wrong_and_keeps_the_file(tmp_path):
    rn.MIN_CLUBS, keep = 4, rn.MIN_CLUBS
    try:
        resolver = _resolver()
        rn.refresh(SEASON, {"National_League": _article(FIRST)}, resolver, tmp_path)
        path = tmp_path / "2627_national-league-north_nl.csv"
        before = path.read_text(encoding="utf-8")

        def refused(article):
            line = rn.refresh(SEASON, {"National_League": article}, resolver, tmp_path)["national-league-north"]
            assert path.read_text(encoding="utf-8") == before, "a refused grid must not touch the file"
            assert line.startswith("refused: ")
            return line

        fewer = {k: v for k, v in FIRST.items() if k != ("BIS", "BRA")}
        assert "fewer matches than committed: 3 against 4" in refused(_article(fewer))
        assert "committed fixture(s) gone" in refused(_article(fewer))
        swapped = {**fewer, ("BRA", "BIS"): "1–0"}           # same count, a fixture replaced
        assert "committed fixture(s) gone, first Bishop's Stortford v Brackley Town" in refused(_article(swapped))
        renamed = dict(CLUBS, BRA="Brackley Town Saints")
        assert "cannot resolve: Brackley Town Saints" in refused(_article(FIRST, clubs=renamed))
        # A name the committed file already carries unresolved is tolerated: the pipeline tolerates it too.
        rn.write(path, [r if r[2] != "Brackley Town" and r[3] != "Brackley Town" else
                        tuple("Brackley Town Saints" if x == "Brackley Town" else x for x in r)
                        for r in rn.rows_for("national-league-north", rn.grids(SEASON, {"National_League": _article(FIRST)})["national-league-north"])])
        assert rn.refresh(SEASON, {"National_League": _article(FIRST, clubs=renamed)}, resolver, tmp_path)[
            "national-league-north"] == "unchanged, 4 matches"
        rn.write(path, rn.rows_for("national-league-north", rn.grids(SEASON, {"National_League": _article(FIRST)})["national-league-north"]))
        before = path.read_text(encoding="utf-8")
        resolver_plus = _resolver(list(CLUBS.values()) + ["Brackley Town Saints"])
        line = rn.refresh(SEASON, {"National_League": _article(FIRST, clubs=renamed)}, resolver_plus, tmp_path)[
            "national-league-north"]
        assert "club list changed, gone: Brackley Town, new: Brackley Town Saints" in line
        doubled = _article(FIRST) + "|match_ALF_BAN=0–0\n"
        assert "listed twice" in refused(doubled.replace("}}\n== National", "|match_ALF_BAN=0–0\n}}\n== National", 1))
    finally:
        rn.MIN_CLUBS = keep


def test_a_small_grid_is_not_a_division():
    g = rn.grids(SEASON, {"National_League": _article(FIRST)})["national-league-north"]
    assert rn.problems(g, None, _resolver()) == ["only 4 clubs in the grid"]


def test_titles_seasons_and_redirects():
    assert rn.article_title(2027, "Northern_Premier_League") == "2026–27 Northern Premier League"
    assert rn.current_season_end_year(datetime.date(2026, 10, 21)) == 2027
    assert rn.current_season_end_year(datetime.date(2027, 6, 30)) == 2027
    assert rn.current_season_end_year(datetime.date(2027, 7, 1)) == 2028
    pages = {rn.RAW_URL.format(title="Old%20Title"): "#REDIRECT [[New Title]]\n",
             rn.RAW_URL.format(title="New%20Title"): "== National League North ==\n"}
    assert rn.fetch_wikitext("Old Title", get=pages.__getitem__).startswith("== National")
    loop = {rn.RAW_URL.format(title="A"): "#REDIRECT [[B]]", rn.RAW_URL.format(title="B"): "#REDIRECT [[A]]"}
    with pytest.raises(RuntimeError):
        rn.fetch_wikitext("A", get=loop.__getitem__)


def test_a_grid_transcluded_from_a_template_page_is_fetched_from_there():
    article = "== National League North ==\n=== Results ===\n{{Main|x}}\n{{2026–27 National League North results}}\n"
    grid = ("{{Sports results\n|team_order=ALF, BAN, BIS, BRA\n" + "\n".join(f"|name_{c}={n}" for c, n in CLUBS.items())
            + "\n|match_ALF_BAN=1–0\n|match_BIS_BRA=2-2\n}}")
    pages = {rn.RAW_URL.format(title="Template%3A2026%E2%80%9327%20National%20League%20North%20results"): grid}
    assert rn._transcluded("{{Main|x}}\n{{2026–27 National League North results}}\n{{Sports results|y}}\n"
                           "{{nowrap|z}}\n{{2025–26 National League North table}}", SEASON) == [
        "Template:2026–27 National League North results"]
    found = rn.grids(SEASON, {"National_League": article}, get=pages.__getitem__)
    assert found["national-league-north"]["codes"] == ["ALF", "BAN", "BIS", "BRA"]
    assert len(found["national-league-north"]["rows"]) == 2
    assert rn.grids(SEASON, {"National_League": article}) == {}, "without a fetcher the transclusion is only reported"


def test_a_self_ranking_table_template_names_its_clubs_without_a_team_order():
    # Wikipedia's Sports table pages with show_matches declare no team order: the clubs are the ones named.
    table = ("<onlyinclude>{{#invoke:Sports table|main|style=WDL\n|update=17 October 2026\n|result1=PRO\n"
             "|name_TEL=[[AFC Telford United F.C.|AFC Telford United]]\n|name_BED=[[Bedford Town F.C.|Bedford Town]]\n"
             "|name_D&R=[[Dagenham & Redbridge F.C.|Dagenham & Redbridge]]\n|name_W&H=Walton & Hersham\n\n"
             "|match_TEL_BED = 0-1\n|match_TEL_D&R =\n|match_D&R_W&H = 2-2\n|match_BED_TEL =\n}}</onlyinclude>")
    article = "== National League North ==\n=== Results ===\n{{2026–27 National League North table|show_matches=only}}\n"
    pages = {rn.RAW_URL.format(title="Template%3A2026%E2%80%9327%20National%20League%20North%20table"): table}
    g = rn.grids(SEASON, {"National_League": article}, get=pages.__getitem__)["national-league-north"]
    assert g["codes"] == ["TEL", "BED", "D&R", "W&H"]
    assert g["rows"] == [("TEL", "BED", 0, 1), ("D&R", "W&H", 2, 2)]
    assert [r[2:4] for r in rn.rows_for("national-league-north", g)] == [
        ("AFC Telford United", "Bedford Town"), ("Dagenham & Redbridge", "Walton & Hersham")]
