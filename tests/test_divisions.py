import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import divisions

PROJECT_ROOT = Path(__file__).parent.parent
DB = PROJECT_ROOT / "data" / "db" / "england.db"


# ── the registry ───────────────────────────────────────────────────────

def test_every_division_id_is_unique_and_slug_shaped():
    ids = [d.division_id for d in divisions.DIVISIONS]
    assert len(ids) == len(set(ids))
    for division_id in ids:
        assert division_id == division_id.lower()
        assert " " not in division_id
        assert not division_id.startswith("-") and not division_id.endswith("-")


def test_the_existing_urls_are_the_division_ids():
    """
    The site has published /division/<slug>/ for years. The id is that
    slug, which is what makes adding the column a change no reader sees.
    """
    for tier, slug in [(1, "premier-league"), (2, "championship"),
                       (3, "league-one"), (4, "league-two"),
                       (5, "national-league")]:
        division = divisions.BY_ID[slug]
        assert division.tier == tier
        assert divisions.sole_division(tier) is division


def test_two_divisions_at_one_level_are_coloured_the_same():
    """They are the same level. Colouring them apart would say otherwise."""
    for tier in divisions.tiers():
        colors = {d.color for d in divisions.by_tier(tier)}
        assert len(colors) == 1, f"tier {tier} has {len(colors)} colours"


def test_a_tier_with_parallel_divisions_has_no_sole_division():
    assert divisions.sole_division(6) is None
    assert len(divisions.by_tier(6)) == 2
    # Five ids at the seventh tier but never five at once: the Southern
    # League Premier was one division until 2017/18 and two after.
    assert len(divisions.by_tier(7)) == 5
    assert len(divisions.by_tier(7, 2015)) == 3
    assert len(divisions.by_tier(7, 2019)) == 4


def test_only_the_downloadable_divisions_carry_a_source_code():
    """
    There is no match-level feed below the fifth tier, so a source_code
    there would send download_all after a file that does not exist.
    """
    for division in divisions.DIVISIONS:
        if division.tier <= 5:
            assert division.source_code, division.division_id
        else:
            assert division.source_code is None, division.division_id


def test_the_download_codes_come_from_the_registry():
    import download
    assert download.TIER_TO_CODE == {1: "E0", 2: "E1", 3: "E2", 4: "E3", 5: "EC"}


# ── the shipped database ───────────────────────────────────────────────

def _conn():
    if not DB.exists():
        pytest.skip("no built database")
    return sqlite3.connect(DB)


def test_every_standings_row_knows_its_division():
    conn = _conn()
    assert conn.execute(
        "SELECT COUNT(*) FROM standings WHERE division_id IS NULL").fetchone()[0] == 0


def test_no_row_claims_a_division_from_another_tier():
    conn = _conn()
    wrong = [
        (division_id, tier) for division_id, tier in conn.execute(
            "SELECT DISTINCT division_id, tier FROM standings")
        if division_id not in divisions.BY_ID
        or divisions.BY_ID[division_id].tier != tier
    ]
    assert not wrong, f"division_id disagrees with tier: {wrong}"


def test_tier_position_equals_position_while_every_tier_is_one_division():
    """
    The invariant that makes the ladder's switch from position to
    tier_position provably a no-op. It stops holding the day a tier gains
    a second division, and this test should then be narrowed to the tiers
    that still have one - not deleted.
    """
    conn = _conn()
    for (tier,) in conn.execute("SELECT DISTINCT tier FROM standings"):
        if divisions.sole_division(tier) is None:
            continue
        mismatched = conn.execute(
            "SELECT COUNT(*) FROM standings WHERE tier = ?"
            " AND tier_position <> position", (tier,)).fetchone()[0]
        assert mismatched == 0, f"tier {tier}"


def test_every_level_is_numbered_from_one_with_no_gaps():
    """
    A club's place on the ladder is its tier_position plus everyone
    above, so a level that skips a number leaves a hole in the ladder and
    one that repeats puts two clubs in the same place.
    """
    conn = _conn()
    for season, tier in conn.execute(
            "SELECT DISTINCT season_end_year, tier FROM standings"):
        places = sorted(r[0] for r in conn.execute(
            "SELECT tier_position FROM standings"
            " WHERE season_end_year = ? AND tier = ?", (season, tier)))
        assert places == list(range(1, len(places) + 1)), f"{season} tier {tier}"


def test_the_era_tiebreak_reaches_the_seasons_it_applies_to():
    """
    The Football League put goals scored ahead of goal difference from
    1992/93 to 1998/99, and twenty-one rows in tiers 2 and 3 were still
    ordered on goal difference - written before the rule was coded and
    never re-ingested, because those seasons' raw files are no longer on
    disk. Two clubs level on points in those seasons must now be ordered
    on goals scored.
    """
    conn = _conn()
    wrong = []
    for season in range(1993, 2000):
        for tier in (2, 3, 4):
            rows = conn.execute(
                "SELECT club_name, position, points, gf FROM standings"
                " WHERE season_end_year = ? AND tier = ? ORDER BY position",
                (season, tier)).fetchall()
            for above, below in zip(rows, rows[1:]):
                if above[2] == below[2] and above[3] < below[3]:
                    wrong.append((season, tier, above[0], below[0]))
    assert not wrong, f"level on points but ordered against goals scored: {wrong}"


# ── the delete bug ─────────────────────────────────────────────────────

def test_loading_one_division_does_not_delete_its_neighbour():
    """
    The single most dangerous line in the tier-6 work. Replacing a
    season's rows keyed on the TIER wipes the other division of that tier
    - silently, because neither table is malformed and no constraint is
    violated. Keyed on the division, it does not.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE standings (season_end_year INT, tier INT,"
                 " division_id TEXT, club_name TEXT)")
    conn.executemany(
        "INSERT INTO standings VALUES (?,?,?,?)",
        [(2027, 6, "national-league-north", "Chester"),
         (2027, 6, "national-league-north", "Buxton"),
         (2027, 6, "national-league-south", "Maidstone United"),
         (2027, 6, "national-league-south", "Chelmsford City")],
    )

    conn.execute(
        "DELETE FROM standings WHERE season_end_year = ? AND tier = ?"
        " AND (division_id = ? OR (division_id IS NULL AND ? IS NULL))",
        (2027, 6, "national-league-south", "national-league-south"),
    )

    survivors = {r[0] for r in conn.execute(
        "SELECT division_id FROM standings WHERE season_end_year = 2027")}
    assert survivors == {"national-league-north"}


# ── the FA allocations, which still settle who plays where now ─────────

ALLOCATIONS = PROJECT_ROOT / "data" / "nls-allocations-2026-27.tsv"


def _allocations():
    if not ALLOCATIONS.exists():
        pytest.skip("no allocations file")
    rows = []
    with ALLOCATIONS.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("division\t"):
                continue
            division, tier, rank, name = line.rstrip("\n").split("\t")
            rows.append((division, int(tier), int(rank), name))
    return rows


def test_the_allocations_hold_every_division_at_its_real_size():
    """
    The parse is geometric - column bands and heights on a page - so what
    proves it worked is each division coming out the size it actually is.
    A lost row is a club the site cannot see.
    """
    sizes = {}
    for division, _, _, _ in _allocations():
        sizes[division] = sizes.get(division, 0) + 1
    assert sizes == {
        "National League": 24,
        "National League North": 24,
        "National League South": 24,
        "Isthmian League Premier": 22,
        "Northern Premier League Premier": 22,
        "Southern League Premier Central": 22,
        "Southern League Premier South": 22,
    }


def test_the_fifth_tier_in_the_allocations_matches_this_repos_own_standings():
    """
    An independent check on the whole extraction. The FA's step 1 column
    and this site's in-progress fifth-tier season are unrelated sources
    for the same 24 clubs, and every name has to resolve.
    """
    conn = _conn()
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    import entities
    resolver = entities.build_resolver(conn)

    season = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    from_db = {r[0] for r in conn.execute(
        "SELECT DISTINCT club_id FROM standings WHERE tier = 5"
        " AND season_end_year = ?", (season,))}
    from_pdf = {resolver.get(entities._normalize(name))
                for _, tier, _, name in _allocations() if tier == 5}
    assert None not in from_pdf, "a fifth-tier name did not resolve"
    assert from_pdf == from_db


def test_every_club_the_allocations_name_now_has_an_identity():
    """
    The roster used to hold these clubs because they had no standings
    rows to hang an identity on. They are in club_master now, so a name
    the FA lists and this project cannot resolve is a gap, not a design.
    """
    conn = _conn()
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    import entities
    resolver = entities.build_resolver(conn)
    missing = [name for _, _, _, name in _allocations()
               if not resolver.get(entities._normalize(name))]
    assert not missing, f"named by the FA and unknown here: {sorted(set(missing))}"


# ── the check that would have caught all of it ─────────────────────────

def _division_seasons(conn):
    """Every (season, tier, division) with its club count and match count."""
    for season, tier, division_id, n_clubs in conn.execute(
            "SELECT season_end_year, tier, division_id, COUNT(*) FROM standings"
            " GROUP BY season_end_year, tier, division_id"):
        n_matches = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE season_end_year = ?"
            " AND tier = ? AND division_id IS ?",
            (season, tier, division_id)).fetchone()[0]
        yield season, tier, division_id, n_clubs, n_matches


def test_no_division_season_holds_more_matches_than_it_can_have():
    """
    n clubs play n*(n-1) fixtures. More than that is not a short file or a
    curtailed season, it is the same matches stored twice - which is what
    happened when the division backfill was run after the ingest rather
    than before it: the season-replacing DELETE missed the rows that had
    no division_id yet, and the insert stacked on top of them. Tier 1 went
    from 28,586 matches to 44,468 without a single error being raised.
    """
    conn = _conn()
    over = [(s, t, d, c, m) for s, t, d, c, m in _division_seasons(conn)
            if m > c * (c - 1)]
    assert not over, f"more matches than fixtures exist: {over}"


def test_a_short_division_season_is_flagged_rather_than_read_as_final():
    """
    The check that would have caught the tier-keyed matches DELETE. Loading
    National League South deleted the North's fixtures, leaving every
    tier-6 season at exactly half its matches - arithmetic that is visible
    the moment the count is compared against the size of the DIVISION.
    Compared against the size of the TIER it was invisible, because a
    44-club tier and a 22-club division are the same wrong answer.

    A division-season with no matches at all is not a failure: there is no
    match-level feed below the fifth tier before 2013 or after 2019.
    """
    conn = _conn()
    unflagged = []
    for season, tier, division_id, n_clubs, n_matches in _division_seasons(conn):
        if n_matches == 0:
            continue
        if n_matches == n_clubs * (n_clubs - 1):
            continue
        complete = conn.execute(
            "SELECT MIN(data_complete) FROM standings WHERE season_end_year = ?"
            " AND tier = ? AND division_id IS ?",
            (season, tier, division_id)).fetchone()[0]
        if complete:
            unflagged.append((season, tier, division_id, n_clubs, n_matches,
                              n_clubs * (n_clubs - 1)))
    assert not unflagged, f"short of fixtures but not flagged: {unflagged}"
