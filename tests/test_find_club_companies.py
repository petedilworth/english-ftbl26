"""
Matching a club to the company that files its accounts.

The whole risk in this step is a confident wrong answer: a supporters'
trust, a dissolved predecessor, or a company that merely shares a town's
name, chosen silently and then attached to a turnover figure. So the
tests are mostly about what the scorer must refuse, and about the state
it reports when it cannot separate two candidates.
"""
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import find_club_companies as fcc                        # noqa: E402


def company(name, sic=("93120",), status="active", number=None):
    return {
        "company_name": name,
        "company_number": number or name[:8].upper().replace(" ", ""),
        "company_status": status,
        "sic_codes": list(sic),
    }


# ── what to ask for ────────────────────────────────────────────────────────

def test_the_place_name_is_asked_for_separately():
    """
    A club's registered name is not reliably its football name: Wimbledon
    file as "The Wimbledon Football Club Limited", so a search for "AFC
    Wimbledon" alone finds nothing.
    """
    terms = fcc.query_terms("AFC Wimbledon")
    assert terms[0] == "AFC Wimbledon"
    assert "Wimbledon" in terms
    assert "wimbledon" in [t.lower() for t in terms]


def test_a_one_word_club_is_asked_for_once():
    assert fcc.query_terms("Marine") == ["Marine"]


def test_the_place_term_drops_only_club_words():
    """The third term is the place: "united" alone would match a third of
    the register."""
    assert fcc.query_terms("Manchester United") == ["Manchester United", "manchester"]
    assert fcc.query_terms("Wingate & Finchley") == ["Wingate & Finchley",
                                                     "wingate finchley"]


# ── what the scorer must refuse ────────────────────────────────────────────

def test_a_company_of_another_name_scores_nothing():
    points, why = fcc.score("Arsenal", company("Chelsea Football Club Limited"))
    assert points == 0
    assert why == ["name does not match"]


def test_the_supporters_trust_is_not_the_club():
    club = fcc.score("Arsenal", company("Arsenal Football Club Limited"))[0]
    trust = fcc.score("Arsenal", company("Arsenal Supporters Trust Limited"))[0]
    assert trust < club
    assert "not the club" in " ".join(
        fcc.score("Arsenal", company("Arsenal Supporters Trust Limited"))[1])


def test_a_dissolved_company_loses_to_a_live_one():
    live = fcc.score("Portsmouth", company("Portsmouth Football Club Limited"))[0]
    dead = fcc.score(
        "Portsmouth",
        company("Portsmouth Football Club Limited", status="dissolved"))[0]
    assert dead < live


def test_the_sport_club_sic_code_outweighs_a_matching_name():
    """
    93120 is the one signal that says a company IS a club rather than
    something named after one - a pub, a property company, a fan site.
    """
    with_sic = fcc.score("Yate Town", company("Yate Town Limited"))[0]
    without = fcc.score("Yate Town", company("Yate Town Limited", sic=("56302",)))[0]
    assert with_sic - without == fcc.POINTS_SIC_CLUB


def test_the_club_company_is_preferred_to_the_holding_company():
    """
    Both are real answers and the holding company is sometimes the right
    one, but only where the club company is dormant - which a search
    result cannot show. So the club company wins by default and the
    holding company is kept as a runner-up for a person to look at.
    """
    club = {"club_id": "arsenal-fc", "name": "Arsenal"}
    result = fcc.rank(club, [
        company("Arsenal Football Club Limited", number="00109244"),
        company("Arsenal Holdings Limited", number="04250459"),
    ])
    assert result["chosen"]["company_number"] == "00109244"
    assert "04250459" in [r["company_number"] for r in result["runners_up"]]


# ── what it says when it cannot tell ───────────────────────────────────────

def test_two_equally_good_candidates_are_sent_for_review():
    club = {"club_id": "marine-fc", "name": "Marine"}
    result = fcc.rank(club, [
        company("Marine Football Club Limited", number="11111111"),
        company("Marine Football Club (1919) Limited", number="22222222"),
    ])
    assert result["state"] == "review", result
    assert result["margin"] < fcc.MIN_MARGIN


def test_a_weak_best_candidate_is_sent_for_review():
    club = {"club_id": "yate-town-fc", "name": "Yate Town"}
    # Active, and named right, but nothing says it is a sport club: a
    # property company that happens to carry the town's name looks like
    # this too.
    result = fcc.rank(club, [company("Yate Town Limited", sic=("68209",))])
    assert result["state"] == "review"
    assert result["chosen"]["score"] < fcc.MIN_CONFIDENT


def test_no_candidate_is_not_found_rather_than_a_guess():
    result = fcc.rank({"club_id": "x-fc", "name": "Barnet"},
                      [company("Totally Unrelated Limited")])
    assert result["state"] == "not_found"
    assert result["chosen"] is None


def test_a_clear_winner_is_chosen():
    club = {"club_id": "arsenal-fc", "name": "Arsenal"}
    result = fcc.rank(club, [
        company("Arsenal Football Club Limited", number="00109244"),
        company("Arsenal Cars Limited", sic=("45112",), number="99999999"),
    ])
    assert result["state"] == "chosen"
    assert result["chosen"]["company_number"] == "00109244"
    assert "SIC 93120" in result["chosen"]["why"]


# ── reading what the fetch wrote ───────────────────────────────────────────

def test_candidates_are_deduped_and_the_richer_record_kept(tmp_path):
    """
    The plain search returns no SIC codes and the advanced search does, so
    a company found by both must keep the copy that can be scored.
    """
    (tmp_path / "marine-fc__0.json").write_text(json.dumps({"items": [
        {"title": "Marine Football Club Limited", "company_number": "11111111",
         "company_status": "active"}]}))
    (tmp_path / "marine-fc__1.json").write_text(json.dumps({"items": [
        {"company_name": "Marine Football Club Limited",
         "company_number": "11111111", "company_status": "active",
         "sic_codes": ["93120"]}]}))
    found = fcc.candidates_for(tmp_path, "marine-fc")
    assert len(found) == 1
    assert found[0]["sic_codes"] == ["93120"]


def test_a_file_that_is_not_json_is_skipped_not_fatal(tmp_path):
    (tmp_path / "marine-fc__1.json").write_text("<html>rate limited</html>")
    assert fcc.candidates_for(tmp_path, "marine-fc") == []


def test_the_targets_are_the_clubs_that_need_one():
    """
    Everyone playing now without accounts, plus every club whose accounts
    were collected by hand without recording which company filed them -
    88 series that cannot otherwise be refreshed, and the only check this
    scorer has against a person's judgement.
    """
    import sqlite3
    db = PROJECT_ROOT / "data" / "db" / "england.db"
    if not db.exists():
        pytest.skip("database not built")
    conn = sqlite3.connect(db)
    rows = fcc.targets(conn)
    ids = {r["club_id"] for r in rows}
    assert len(ids) == len(rows), "a club appears twice"

    last = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    # club_id is nullable in standings: a club this project cannot resolve
    # has a table row and no identity, and cannot be looked up by name.
    playing = {r[0] for r in conn.execute(
        "SELECT DISTINCT club_id FROM standings"
        " WHERE season_end_year = ? AND club_id IS NOT NULL", (last,))}
    with_accounts = {r[0] for r in conn.execute(
        "SELECT DISTINCT club_id FROM club_finances")}
    assert playing <= ids
    assert with_accounts <= ids
    assert all(r["terms"] for r in rows), "a club with nothing to search for"


def test_the_entity_a_person_already_named_wins():
    """
    88 clubs' accounts were read by hand from a named company without its
    number. That name is a person's answer to this exact question, so it
    settles the row rather than leaving it for the same person to decide
    again - and it is what makes Arsenal's holding company the right
    answer for Arsenal, where the default is the club company.
    """
    club = {"club_id": "arsenal-fc", "name": "Arsenal",
            "known_entity": "Arsenal Holdings Limited"}
    result = fcc.rank(club, [
        company("Arsenal Football Club Public Limited Company", number="00109244"),
        company("Arsenal Holdings Limited", number="04250459"),
    ])
    assert result["state"] == "chosen"
    assert result["chosen"]["company_number"] == "04250459"
    assert "read from" in result["chosen"]["why"]


def test_the_holding_company_is_not_confused_with_the_club_company():
    """
    "West Ham United Holdings Limited" and "West Ham United Limited" are
    two companies. The hand-named entity must match one of them, not
    whichever comes first.
    """
    club = {"club_id": "west-ham-united-fc", "name": "West Ham United",
            "known_entity": "West Ham United Holdings Limited"}
    result = fcc.rank(club, [
        company("West Ham United Limited", number="11111111"),
        company("West Ham United Holdings Limited", number="22222222"),
    ])
    assert result["chosen"]["company_number"] == "22222222"
    assert "read from" not in result["runners_up"][0]["why"]
