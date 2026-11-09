"""
The allocation: the table on a day, the place counted down it, and the
browser's copy of the arithmetic agreeing with this one.
"""

import datetime
import json
import random
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import aggregate  # noqa: E402
import allocation as al  # noqa: E402

ROOT = Path(__file__).parent.parent
REAL_DB = ROOT / "data" / "db" / "england.db"
PROCESS_JS = ROOT / "static" / "allocation-process.js"
D = datetime.date


def _season(rules="gd", complete=False, matches=(), final=None, first="2000-08-12", last="2001-05-05"):
    """Four clubs in one division, named so that name order is a, b, c, d."""
    data = {
        "season": 2001, "first": first, "last": last, "complete": complete,
        "clubs": ["a-fc", "b-fc", "c-fc", "d-fc"], "tiers": [1], "sizes": [4],
        "divisions": ["Premier League"], "rules": [[3, 3, 1, rules]],
        "m": [n for match in matches for n in match],
    }
    if final:
        data["final"] = final
    return data


def _order(data, date):
    return [data["clubs"][r["club"]] for r in al.table(data, date)[0]["rows"]]


# ── The table on a day ────────────────────────────────────────────────────

def test_the_table_counts_only_results_up_to_the_end_of_that_day():
    # day, home, away, home goals, away goals
    data = _season(matches=[(0, 3, 0, 2, 0), (7, 0, 3, 5, 0)])
    assert _order(data, D(2000, 8, 12))[0] == "d-fc"            # after day one, d have won
    assert _order(data, D(2000, 8, 18))[0] == "d-fc"            # the day before the return
    rows = {data["clubs"][r["club"]]: r for r in al.table(data, D(2000, 8, 19))[0]["rows"]}
    assert rows["a-fc"]["position"] == 1 and rows["a-fc"]["points"] == 3 and rows["a-fc"]["gf"] == 5
    assert rows["d-fc"]["played"] == 2 and rows["d-fc"]["lost"] == 1


def test_clubs_the_rules_cannot_separate_stay_in_name_order():
    # Nobody has played: all level on nothing, so the table is alphabetical.
    assert _order(_season(matches=[(30, 0, 1, 1, 0)]), D(2000, 8, 12)) == ["a-fc", "b-fc", "c-fc", "d-fc"]


def test_each_era_breaks_a_tie_its_own_way():
    day = D(2000, 8, 12)
    # Goal average against goal difference. c win 2-1: difference +1, average 2.0.
    # d win 5-3: difference +2, average 1.67. Before 1976/77 c are top; after it, d.
    close = [(0, 2, 0, 2, 1), (0, 3, 1, 5, 3)]
    assert _order(_season("ga", matches=close), day)[0] == "c-fc"
    assert _order(_season("gd", matches=close), day)[0] == "d-fc"
    # Goal difference against goals scored. c win 3-0: difference +3, three scored.
    # d win 5-3: difference +2, five scored. The Football League of the 1990s puts d top.
    clean = [(0, 2, 0, 3, 0), (0, 3, 1, 5, 3)]
    assert _order(_season("gd", matches=clean), day)[0] == "c-fc"
    assert _order(_season("gs", matches=clean), day)[0] == "d-fc"
    # A club that has conceded nothing is divided by one, not by nought.
    assert _order(_season("ga", matches=clean), day)[0] == "c-fc"


def test_the_points_rule_is_the_seasons_own():
    data = _season(matches=[(0, 0, 1, 1, 0), (0, 2, 3, 2, 2)])
    data["rules"] = [[2, 3, 1, "gd"]]                                           # the Alliance's away-win experiment
    rows = {data["clubs"][r["club"]]: r["points"] for r in al.table(data, D(2000, 8, 12))[0]["rows"]}
    assert rows == {"a-fc": 2, "b-fc": 0, "c-fc": 1, "d-fc": 1}
    data["m"] = [0, 0, 1, 0, 1]
    assert al.table(data, D(2000, 8, 12))[0]["rows"][0]["points"] == 3          # b won away


def test_a_finished_season_is_the_final_table_from_its_last_day_on():
    # The results say a are top. The record says they were docked and finished last.
    final = [[2, 2, 0, 0, 4, 0, 6], [2, 1, 0, 1, 2, 2, 3], [2, 0, 0, 2, 0, 4, 0], [2, 2, 0, 0, 4, 0, -4]]
    data = _season(complete=True, final=final, matches=[(0, 3, 0, 4, 0)], last="2000-08-12")
    data["clubs"] = ["b-fc", "c-fc", "d-fc", "a-fc"]                             # final order, as season_data writes it
    table = al.table(data, D(2000, 8, 12))[0]
    assert table["final"] and [data["clubs"][r["club"]] for r in table["rows"]] == ["b-fc", "c-fc", "d-fc", "a-fc"]
    assert table["rows"][3]["points"] == -4
    # And all summer.
    assert al.table(data, D(2000, 7, 30).replace(year=2001))[0]["final"]
    # A season still being played has no final table to use.
    live = dict(data, complete=False)
    assert not al.table(live, D(2000, 8, 12))[0]["final"]


# ── The date the process uses ─────────────────────────────────────────────

INDEX = {"epoch": "1958-08-23", "latest": "2026-11-08",
         "seasons": [[1959, "1958-08-23", "1959-05-07", 1], [1960, "1959-08-22", "1960-05-06", 1],
                     [2027, "2026-08-14", "2026-11-08", 0]]}


def test_the_summer_belongs_to_the_season_that_has_just_ended():
    assert al.season_for(INDEX, D(1958, 8, 23)) == 1959
    assert al.season_for(INDEX, D(1959, 7, 1)) == 1959
    assert al.season_for(INDEX, D(1959, 8, 21)) == 1959
    assert al.season_for(INDEX, D(1959, 8, 22)) == 1960
    assert al.season_for(INDEX, D(1958, 8, 22)) is None


def test_a_birth_before_the_record_takes_the_same_day_in_its_first_season():
    assert al.stand_in(INDEX, D(1950, 12, 25)) == D(1958, 12, 25)     # after the first day: that year
    assert al.stand_in(INDEX, D(1950, 3, 14)) == D(1959, 3, 14)       # before it: the year after
    assert al.stand_in(INDEX, D(1950, 8, 23)) == D(1958, 8, 23)       # the first day itself
    assert al.stand_in(INDEX, D(1950, 8, 22)) == D(1959, 8, 22)       # the day before it
    assert al.stand_in(INDEX, D(1940, 2, 29)) == D(1959, 2, 28)       # 1959 has no 29 February
    assert al.process_date(INDEX, D(1987, 3, 14)) == D(1987, 3, 14)
    assert al.process_date(INDEX, D(2030, 1, 1)) == D(2026, 11, 8)    # nothing after the last result


def test_the_place_is_the_day_count_modulo_the_number_of_clubs():
    data = _season(matches=[(0, 3, 0, 2, 0)], first="1958-08-23", last="1959-05-07")
    for days, place in ((0, 1), (1, 2), (3, 4), (4, 1), (10, 3)):
        got = al.allocate(INDEX, data, D(1958, 8, 23) + datetime.timedelta(days=days))
        assert (got["day"], got["clubs"], got["place"]) == (days, 4, place)
    # Day nought, place one: the club top of the table that evening.
    assert al.allocate(INDEX, data, D(1958, 8, 23))["club"] == "d-fc"
    old = al.allocate(INDEX, data, D(1950, 12, 25))
    assert old["stand_in"] and old["used"] == "1958-12-25" and old["born"] == "1950-12-25"


# ── From a database ───────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE club_master (club_id TEXT PRIMARY KEY, canonical_name TEXT)")
    conn.execute("CREATE TABLE standings (season_end_year INT, tier INT, division_name TEXT, club_id TEXT,"
                 " club_name TEXT, position INT, played INT, won INT, drawn INT, lost INT, gf INT, ga INT,"
                 " gd INT, points INT, status TEXT)")
    conn.execute("CREATE TABLE matches (season_end_year INT, tier INT, match_date TEXT, home_club_id TEXT,"
                 " away_club_id TEXT, home_name TEXT, away_name TEXT, fthg INT, ftag INT, ftr TEXT)")
    for cid in ("alpha", "beta", "gamma", "delta"):
        conn.execute("INSERT INTO club_master VALUES (?, ?)", (cid, cid.capitalize()))
    # 1975/76, second tier: two points for a win and goal average.
    for pos, cid, pts in ((1, "beta", 4), (2, "alpha", 2), (3, "delta", 2), (4, "gamma", 0)):
        conn.execute("INSERT INTO standings VALUES (1976, 2, 'Second Division', ?, ?, ?, 2, 0, 0, 0, 0, 0, 0, ?, 'Stayed')",
                     (cid, cid.capitalize(), pos, pts))
    for when, home, away, hg, ag in (("1975-08-16", "alpha", "beta", 0, 1), ("1975-08-16", "gamma", "delta", 0, 2),
                                     ("1975-08-23", "beta", "gamma", 3, 0), ("1975-08-23", "delta", "alpha", 0, 1)):
        conn.execute("INSERT INTO matches VALUES (1976, 2, ?, ?, ?, '', '', ?, ?, '')", (when, home, away, hg, ag))
    return conn


def test_a_season_file_lists_clubs_in_final_order_with_that_seasons_rules():
    conn = _db()
    data = al.season_data(conn, 1976)
    assert data["clubs"] == ["beta", "alpha", "delta", "gamma"]
    assert data["tiers"] == [2] and data["sizes"] == [4] and data["divisions"] == ["Second Division"]
    assert data["rules"] == [[2, 2, 1, "ga"]]
    assert (data["first"], data["last"], data["complete"]) == ("1975-08-16", "1975-08-23", True)
    assert len(data["m"]) == 4 * 5 and data["m"][:5] == [0, 1, 0, 0, 1]      # alpha 0-1 beta, as numbers
    assert data["final"][0] == [2, 0, 0, 0, 0, 0, 4]
    assert al.season_data(conn, 1999) is None
    idx = al.index(conn)
    assert idx == {"epoch": "1975-08-16", "latest": "1975-08-23", "seasons": [[1976, "1975-08-16", "1975-08-23", 1]]}
    assert al.allocatable(conn) == ["alpha", "beta", "delta", "gamma"]


def test_the_whole_process_against_a_database():
    conn = _db()
    first = al.run(conn, D(1975, 8, 16))          # day 0: top after one round, on goal average
    assert (first["place"], first["club"], first["tier"], first["division"]) == (1, "delta", 2, "Second Division")
    assert not first["table"][0]["final"]
    later = al.run(conn, D(1976, 1, 1))           # the season is over in this little world: the recorded table
    assert later["table"][0]["final"] and later["club"] == ["beta", "alpha", "delta", "gamma"][later["day"] % 4]


def test_a_database_without_dated_matches_cannot_run_the_process():
    conn = sqlite3.connect(":memory:")
    assert not al.available(conn)
    conn.execute("CREATE TABLE matches (season_end_year INT, tier INT, match_date TEXT, home_club_id TEXT,"
                 " away_club_id TEXT, fthg INT, ftag INT)")
    conn.execute("INSERT INTO matches VALUES (2000, 5, '1999-08-14', 'a', 'b', 1, 0)")    # fifth tier: not the ninety-two
    conn.execute("INSERT INTO matches VALUES (2000, 1, NULL, 'a', 'b', 1, 0)")            # undated
    assert not al.available(conn) and al.index(conn) is None


# ── Against the record itself ─────────────────────────────────────────────

needs_record = pytest.mark.skipif(not REAL_DB.exists(), reason="england.db not present")


@pytest.fixture(scope="module")
def record():
    conn = sqlite3.connect(REAL_DB)
    idx = al.index(conn)
    names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))
    files = {entry[0]: al.season_data(conn, entry[0]) for entry in idx["seasons"]}
    yield conn, idx, names, files
    conn.close()


@needs_record
def test_every_result_added_up_gives_the_table_that_was_recorded(record):
    """
    The check that the table on a day can be trusted: run every finished
    season to its last day from the results alone and the order must be
    the final table in the standings - goal average, goal difference,
    goals scored and all. The exceptions are exactly the ones the module
    says it does not attempt: a division where points were deducted, and
    a division settled on points per game.
    """
    conn, idx, names, files = record
    docked = {(r[0], r[1]) for r in conn.execute(
        "SELECT season_end_year, tier FROM standings WHERE COALESCE(points_deducted, 0) != 0")}
    checked = 0
    for season, _first, last, complete in idx["seasons"]:
        if not complete:
            continue
        data = dict(files[season], complete=False)        # ignore the recorded table: add the results up
        start = 0
        for t, division in enumerate(al.table(data, D.fromisoformat(last), names)):
            size = data["sizes"][t]
            tier = data["tiers"][t]
            if (season, tier) not in docked and not aggregate.settled_on_ppg(tier, season):
                assert [r["club"] for r in division["rows"]] == list(range(start, start + size)), (season, tier)
                checked += 1
            start += size
    assert checked > 200, "expected most of the record to be checkable"


@needs_record
def test_the_first_day_of_the_record_and_one_ordinary_saturday(record):
    conn, idx, names, files = record
    assert idx["epoch"] == "1958-08-23"
    first = al.allocate(idx, files[1959], D(1958, 8, 23), names)
    assert (first["day"], first["place"], first["clubs"]) == (0, 1, 92)
    saturday = al.allocate(idx, files[1987], D(1987, 3, 14), names)
    assert (saturday["day"], saturday["clubs"], saturday["place"]) == (10430, 92, 35)
    assert saturday["club"] == "birmingham-city-fc" and saturday["division"] == "Second Division"


# ── The browser's copy ────────────────────────────────────────────────────

NODE = shutil.which("node")
PARITY = r"""
const fs = require("fs"), path = require("path");
const P = require(path.resolve(process.argv[2])), dir = process.argv[3];
const read = name => JSON.parse(fs.readFileSync(path.join(dir, name)));
const idx = read("index.json"), names = read("names.json"), cache = {};
const out = read("dates.json").map(born => {
  const used = P.processDate(idx, born), season = P.seasonFor(idx, used);
  cache[season] = cache[season] || read(season + ".json");
  const a = P.allocate(idx, cache[season], born, names);
  return [born, a.used, a.standIn, a.day, a.clubs, a.place, a.club, a.tier, a.position, a.row.points, a.row.played];
});
process.stdout.write(JSON.stringify(out));
"""


def _both(tmp_path, idx, names, files, dates):
    """The same dates through the Python and through static/allocation-process.js under Node."""
    (tmp_path / "index.json").write_text(json.dumps(idx))
    (tmp_path / "names.json").write_text(json.dumps(names))
    (tmp_path / "dates.json").write_text(json.dumps([d.isoformat() for d in dates]))
    for season, data in files.items():
        (tmp_path / f"{season}.json").write_text(json.dumps(data))
    (tmp_path / "parity.js").write_text(PARITY)
    done = subprocess.run([NODE, str(tmp_path / "parity.js"), str(PROCESS_JS), str(tmp_path)],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    theirs = json.loads(done.stdout)
    ours = []
    for born in dates:
        a = al.allocate(idx, files[al.season_for(idx, al.process_date(idx, born))], born, names)
        ours.append([a["born"], a["used"], a["stand_in"], a["day"], a["clubs"], a["place"], a["club"], a["tier"],
                     a["position"], a["row"]["points"], a["row"]["played"]])
    return ours, theirs


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_the_browser_and_the_python_agree_on_a_small_league(tmp_path):
    conn = _db()
    idx, names = al.index(conn), dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))
    dates = [D(1975, 8, 16) + datetime.timedelta(days=n) for n in range(0, 40)] + [D(1960, 2, 29), D(1975, 8, 15)]
    ours, theirs = _both(tmp_path, idx, names, {1976: al.season_data(conn, 1976)}, dates)
    assert ours == theirs


@needs_record
@pytest.mark.skipif(not NODE, reason="node not installed")
def test_the_browser_and_the_python_agree_across_the_record(tmp_path, record):
    """
    The page runs static/allocation-process.js; the rule is written in
    src/allocation.py. Two thousand dates of birth, from before the record
    to after it, through both: one disagreement about one club fails this.
    """
    _conn, idx, names, files = record
    rng = random.Random(1958)
    span = (D(2027, 6, 1) - D(1925, 1, 1)).days
    dates = sorted({D(1925, 1, 1) + datetime.timedelta(days=rng.randrange(span)) for _ in range(2000)})
    dates += [D(1958, 8, 22), D(1958, 8, 23), D(1940, 2, 29), D(1960, 2, 29), D.fromisoformat(idx["latest"])]
    ours, theirs = _both(tmp_path, idx, names, files, dates)
    assert len(theirs) == len(dates)
    assert ours == theirs
