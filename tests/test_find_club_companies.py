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

def test_the_club_name_is_never_asked_for_unqualified_on_its_own():
    """
    The failure of the first real run. "Chelsea" matches 2,772 companies;
    the advanced search returns them alphabetically and Chelsea Football
    Club Limited is not in the first 100. So every advanced query carries
    a football word, and the bare name only ever goes to the
    relevance-ranked search.
    """
    qs = fcc.queries("Chelsea")
    bare = [q for q in qs if q == "adv:Chelsea"]
    assert not bare, "an unqualified name_includes query cannot find the club"
    assert "plain:Chelsea" in qs
    assert "adv:Chelsea football club" in qs
    assert "adv:Chelsea fc" in qs
    assert "sic:Chelsea" in qs


def test_both_football_club_and_fc_are_asked_for():
    """
    Neither spelling covers both: "The Reading Football Club Limited" and
    "Burnley FC Holdings Limited" each miss the other's query.
    """
    qs = fcc.queries("Burnley")
    assert "adv:Burnley football club" in qs
    assert "adv:Burnley fc" in qs


def test_the_place_name_is_asked_for_separately():
    """
    A club's registered name is not reliably its football name: Wimbledon
    file as "The Wimbledon Football Club Limited", so asking only about
    "AFC Wimbledon" finds nothing.
    """
    qs = fcc.queries("AFC Wimbledon")
    assert "plain:AFC Wimbledon" in qs
    assert "adv:Wimbledon football club" in qs


def test_the_hand_named_entity_is_asked_for_by_name():
    """
    "Football Ventures (Whites) Limited" is Bolton Wanderers and shares
    not one word with them. No query built from the club's name can find
    it, so the recorded name is asked for directly.
    """
    qs = fcc.queries("Bolton Wanderers", "Football Ventures (Whites) Limited")
    assert "plain:Football Ventures (Whites) Limited" in qs


def test_a_query_is_not_asked_twice_in_different_case():
    """A one-word club reduces to its own lower-cased name; the search is
    case-insensitive, so paying for both would double the run."""
    qs = fcc.queries("Chelsea")
    assert len(qs) == len({q.lower() for q in qs})


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
    assert all(r["queries"] for r in rows), "a club with nothing to search for"
    # Every club gets the relevance search and both name spellings; the
    # bare name alone was what failed on real data.
    for r in rows:
        kinds = {q.split(":", 1)[0] for q in r["queries"]}
        assert {"plain", "adv", "sic"} <= kinds, r["club_id"]


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


# ── another sport, which is how this scorer failed on real data ────────────

def test_a_rugby_club_is_not_the_football_club():
    """
    Middlesbrough Rugby Union Football Club scored 84 and was chosen
    without review on the first real run. Two signals conspired: SIC
    93120 is "activities of sport clubs" and names no sport, and a rugby
    club is constitutionally a "Rugby Football Club", which collected the
    bonus meant for football.
    """
    points, why = fcc.score("Middlesbrough",
                            company("Middlesbrough Rugby Union Football Club Limited"))
    assert points == 0
    assert why == ["names a different sport"]


@pytest.mark.parametrize("name", [
    "Barnsley Gymnastics Club Limited",
    "Woking Golf Club Limited",
    "Darlington Cricket and Athletic Club C.I.C.",
    "Stourbridge Lawn Tennis and Squash Club Limited",
    "Workington Town Rugby League Football Club,Limited",
    "Macclesfield Town Basketball Club Community Interest Company",
    "City of Salisbury Athletics and Running Club Ltd",
])
def test_every_other_sport_that_was_chosen_for_real_is_refused(name):
    """Each of these was a confident match on the first run."""
    club = name.split()[0]
    assert fcc.score(club, company(name))[0] == 0


def test_athletic_is_still_a_football_word():
    """
    Wigan Athletic, Charlton Athletic, Oldham Athletic. Only the plural
    names the other sport, and refusing the singular would refuse three
    dozen real clubs.
    """
    assert fcc.score("Wigan Athletic",
                     company("Wigan Athletic A.F.C. Limited"))[0] > 0
    assert fcc.score("Salisbury City",
                     company("City of Salisbury Athletics Club Ltd"))[0] == 0


def test_a_company_named_only_for_the_place_is_not_a_club():
    """
    "Chelsea Limited" matches "Chelsea" exactly and is not a football
    club. 74 clubs on this site are named for one common English word, so
    an exact name match cannot stand on its own.
    """
    assert fcc.score("Chelsea", company("Chelsea Limited", sic=("70100",)))[0] == 0
    assert fcc.score("Liverpool", company("Liverpool Limited", sic=()))[0] == 0


def test_a_sport_club_named_only_for_the_place_is_reviewable_not_choosable():
    """
    It might be the club. Nothing in the name says so, and the SIC code
    covers every sport, so it goes to a person rather than into the data.
    """
    club = {"club_id": "walton-and-hersham-fc", "name": "Walton & Hersham"}
    result = fcc.rank(club, [company("Walton and Hersham 2019 Limited")])
    assert result["state"] == "review"
    assert "nothing in the name says football" in result["chosen"]["why"]


def test_the_hand_named_entity_still_wins_without_a_football_word():
    """
    Arsenal Holdings, Tottenham Hotspur Limited, Millwall Holdings: a
    person named these, which outranks any inference from the name.
    """
    club = {"club_id": "arsenal-fc", "name": "Arsenal",
            "known_entity": "Arsenal Holdings Limited"}
    result = fcc.rank(club, [company("Arsenal Holdings Limited", number="04250459")])
    assert result["state"] == "chosen"
    assert result["chosen"]["company_number"] == "04250459"
