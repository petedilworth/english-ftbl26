#!/usr/bin/env python3
"""
Match clubs to the legal entities that file their accounts.

WHY THIS IS THE HARD PART. The site's thinnest data is money: 91 clubs of
355 have any accounts at all, and below the fourth tier it is six clubs
and then two. Collecting more by hand does not scale, and collecting more
automatically fails at the first step rather than the last, because
Companies House knows companies and this project knows clubs, and the
join between them is not the name. Arsenal's accounts are filed by
Arsenal Holdings Limited. A search for "Arsenal" returns dozens of
companies. Which entity filed changes the answer by tens of millions -
finances.py says so at the top of the file - so a wrong match is worse
than no match, and the mapping is a reviewed artefact rather than a
lookup done at fetch time.

THE SPLIT, AND WHY IT IS THIS ONE. api.company-information.service.gov.uk
is refused at this environment's proxy, so the fetching happens on a
machine that can reach it (scripts/fetch_company_candidates.ps1) and
writes one JSON file per query, and every judgement happens here, in the
repository, under test. That is the same division as the Wikipedia work,
and it is the right one for the same reason: the fetch is dumb and
repeatable, the scoring is the part that can be wrong quietly.

    python3 scripts/find_club_companies.py targets > data/companies/targets.tsv
    # (that file is committed, so the fetch needs no Python)
    # ... run the PowerShell fetch on a machine with network access ...
    python3 scripts/find_club_companies.py score DIRECTORY_OF_JSON

WHAT COMES OUT. data/club-companies.tsv, one row per club: the chosen
company, its status and SIC codes, the score, and every runner-up. A row
whose top two candidates are close, or whose best candidate is weak, is
marked `review` and is not used until a person has looked at it.

WHAT THIS CANNOT REACH, STATED HERE RATHER THAN DISCOVERED LATER. Small
clubs file under the small-company or micro-entity regime, which carries
no profit-and-loss account: no turnover, no wages. Many fan-owned clubs
are Community Benefit Societies, which file with the FCA and are not on
Companies House at all. Both are outcomes to record - a club that
discloses nothing is a fact about the club - but the figure-bearing
coverage this can add lands mostly in tiers 3 to 5.
"""

import argparse
import csv
import json
import logging
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DB = PROJECT_ROOT / "data" / "db" / "england.db"
OUT = PROJECT_ROOT / "data" / "club-companies.tsv"

logger = logging.getLogger("find_club_companies")

# 93120 is "activities of sport clubs" and is the single strongest signal
# that a company IS a club rather than something named after one. The
# others are the near misses that a real club sometimes files under.
SIC_CLUB = "93120"
SIC_NEARBY = {"93110", "93130", "93199", "93290"}

# Words that name a body attached to a club rather than the club: the
# supporters' trust, the community foundation, the academy, the women's
# team where it is separately incorporated. Each of these files its own
# accounts, and each would be the wrong answer.
NOT_THE_CLUB = re.compile(
    r"\b(supporters?|trust|foundation|charity|charitable|academy|youth|"
    r"juniors?|ladies|women'?s|social club|sports? and social|travel|"
    r"catering|hospitality|events|property|properties|developments?)\b")

# ANOTHER SPORT ENTIRELY, which is the failure this scorer made on its
# first real run: 18 of 167 confident matches were rugby clubs, a golf
# club, a gymnastics school, a cricket club and a tennis and squash club.
#
# Two things conspired. SIC 93120 is "activities of sport clubs" and says
# nothing about WHICH sport, so it was worth 40 points to a bowls club.
# And rugby clubs are constitutionally named "... Rugby Football Club",
# which collected the naming bonus meant for football. Middlesbrough
# Rugby Union Football Club scored 84 and was chosen without review.
#
# So this disqualifies rather than penalises: a company naming a
# different sport is not the club, whatever else it has going for it.
# "athletic" is deliberately absent - Wigan Athletic, Charlton Athletic,
# Oldham Athletic - while "athletics" is present, which is the running
# club it is easy to confuse them with.
ANOTHER_SPORT = re.compile(
    r"\b(rugby|rfc|rufc|arlfc|rfl|gymnastics?|cricket|golf|tennis|squash|"
    r"bowls|bowling|hockey|netball|basketball|athletics|swimming|boxing|"
    r"rowing|sailing|angling|darts|snooker|cycling|motor|car club|"
    r"greyhound|equestrian|badminton|lacrosse|handball|futsal)\b")

# A company that is plausibly a FOOTBALL club specifically. Used where a
# name match alone is too thin to stand on: "Barnsley Gymnastics Club"
# contains every word of "Barnsley", and 74 club names on this site are a
# single common English place name.
FOOTBALL_WORD = re.compile(
    r"\b(football|soccer|fc|f\.c|afc|a\.f\.c|united|city|town|rovers|"
    r"athletic|wanderers|albion|county|argyle|orient|hotspur|villa|"
    r"forest|alexandra|palace|wednesday|thistle|borough|olympic|nomads)\b")

# Company-form words, dropped before the name is compared. "Limited" tells
# you nothing about which club it is.
FORM = re.compile(
    r"\b(limited|ltd|plc|llp|company|co|holdings?|group|the|and|&)\b")

# The legal form ONLY, for comparing against the entity a person named.
# FORM also drops "holdings" and "group", which is right for asking
# whether a company is named after the club and wrong for asking whether
# it is the company a person read the accounts from: "West Ham United
# Holdings Limited" and "West Ham United Limited" are two companies, and
# eighteen of the ninety hand-named entities are holding companies, plc's
# or year-suffixed successors that differ from the club company in
# exactly the words FORM throws away.
LEGAL_FORM = re.compile(
    r"\b(limited|ltd|plc|public limited company|llp|the)\b")


def _legal_tokens(name: str) -> set[str]:
    text = LEGAL_FORM.sub(" ", _normalise(name))
    return {t for t in text.split() if t}

# Club-type words, dropped to get at the place name. Kept as a separate
# list from FORM because they are worth points when they MATCH and worth
# nothing when they are all that matches: every third club is a "united".
CLUB_TYPE = re.compile(
    r"\b(fc|f\.c\.?|afc|a\.f\.c\.?|football|club|united|town|city|rovers|"
    r"athletic|wanderers|albion|county|rangers|borough|association)\b")


def _normalise(name: str) -> str:
    text = name.lower().replace(".", " ").replace("&", " and ")
    return re.sub(r"[^a-z0-9 ]", " ", text)


def _tokens(name: str, drop_club_type: bool = False) -> list[str]:
    text = _normalise(name)
    text = FORM.sub(" ", text)
    if drop_club_type:
        text = CLUB_TYPE.sub(" ", text)
    return [t for t in text.split() if t]


def queries(name: str, known_entity: str = "") -> list[str]:
    """
    What to ask Companies House for, as `kind:term` pairs.

    THE LESSON FROM THE FIRST REAL RUN. Asking for the club's name alone
    does not find the club. "Chelsea" matches 2,772 companies; the
    advanced search returns them alphabetically and the plain search by
    its own relevance, and Chelsea Football Club Limited was in neither
    the first 100 nor the first 30. Nor were Liverpool, Reading, Barnsley
    or Middlesbrough. The scorer was then picking the best of a list that
    did not contain the answer, which is how a rugby club came to be
    chosen for Middlesbrough.

    So the name is qualified before it is sent, three ways, because no
    one of them covers every club:

      football club  finds "The Reading Football Club Limited"
      fc             finds "Burnley FC Holdings Limited", which the
                     first spelling misses
      SIC 93120      finds a club whose name says neither, by filtering
                     2,772 companies down to the sport clubs among them

    Plus the club's own name on the relevance-ranked search, which is
    what finds the clubs whose registered name is nothing like their
    football one, and the hand-recorded entity where there is one:
    "Football Ventures (Whites) Limited" is Bolton Wanderers and contains
    not one word of it.
    """
    out = [f"plain:{name}"]

    # The place name without the club type, for "AFC Wimbledon" filing as
    # "The Wimbledon Football Club Limited". Falls back to the full name
    # where stripping leaves nothing useful.
    place = " ".join(_tokens(name, drop_club_type=True)) or name
    stem = re.sub(r"^(AFC|A\.F\.C\.)\s+", "", name).strip() or name

    for term in [stem, place]:
        out.append(f"adv:{term} football club")
        out.append(f"adv:{term} fc")
        out.append(f"sic:{term}")

    if known_entity:
        out.append(f"plain:{known_entity}")

    # Case-insensitively, because the search is: "Chelsea" and the
    # lower-cased place name it reduces to are one query, not two, and
    # paying for both doubles a 250-club run for nothing.
    seen, unique = set(), []
    for q in out:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique


def targets(conn: sqlite3.Connection) -> list[dict]:
    """
    The clubs worth asking about: everyone playing now without accounts,
    plus everyone whose accounts were collected by hand without recording
    which company filed them.

    The second group is not busywork. Three of the 91 clubs on file carry
    a company number, so 88 hand-collected series cannot be refreshed
    automatically, and those 88 are also the check on this scorer: it has
    to land on the entity a person already chose.
    """
    last = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    rows = conn.execute(
        """
        SELECT m.club_id, m.canonical_name, s.tier,
               EXISTS(SELECT 1 FROM club_finances f
                       WHERE f.club_id = m.club_id) AS has_accounts,
               (SELECT f.entity_name FROM club_finances f
                 WHERE f.club_id = m.club_id AND f.entity_name IS NOT NULL
                 LIMIT 1) AS known_entity,
               (SELECT f.company_number FROM club_finances f
                 WHERE f.club_id = m.club_id
                   AND f.company_number IS NOT NULL AND f.company_number <> ''
                 LIMIT 1) AS known_number
          FROM club_master m
          LEFT JOIN standings s
            ON s.club_id = m.club_id AND s.season_end_year = ?
         WHERE s.club_id IS NOT NULL
            OR EXISTS(SELECT 1 FROM club_finances f WHERE f.club_id = m.club_id)
         ORDER BY s.tier, m.canonical_name
        """,
        (last,),
    ).fetchall()

    out = []
    for club_id, name, tier, has_accounts, entity, number in rows:
        # A club whose number was already recorded by hand stays in the
        # list: it is the only ground truth the scorer can be checked
        # against, and cmd_score reports agreement rather than overwriting.
        out.append({
            "club_id": club_id,
            "name": name,
            "tier": tier if tier is not None else "",
            "has_accounts": int(bool(has_accounts)),
            "known_entity": entity or "",
            "known_number": number or "",
            "queries": queries(name, entity or ""),
        })
    return out


# ── scoring ────────────────────────────────────────────────────────────────

# Every weight is a whole number of points with a reason, so a mapping can
# be argued with. The name match is worth more than any single signal
# because it is the only one that says WHICH club.
POINTS_SIC_CLUB = 40
POINTS_SIC_NEARBY = 12
POINTS_ACTIVE = 20
POINTS_DISSOLVED = -45
POINTS_FOOTBALL_CLUB = 22
POINTS_FC = 12
POINTS_HOLDINGS = -6          # the club company wins by default; see below
POINTS_NOT_THE_CLUB = -35
POINTS_NAME_EXACT = 45
POINTS_NAME_ALL_TOKENS = 30
POINTS_NAME_PARTIAL = 12
# The 88 clubs whose accounts were read by hand recorded WHICH entity they
# were read from, without its number. That name is a person's answer to
# exactly this question, so a candidate matching it wins outright - and
# these clubs stop being ambiguous cases for a person to re-decide.
POINTS_KNOWN_ENTITY = 60

# Below this, the best candidate is not good enough to use unreviewed;
# within this, the top two are too close to separate mechanically.
MIN_CONFIDENT = 70
MIN_MARGIN = 15


def score(club_name: str, candidate: dict,
          known_entity: str = "") -> tuple[int, list[str]]:
    """
    Points, and the reasons for them.

    The reasons are returned rather than logged because they are what a
    person reviewing an ambiguous row actually needs: "active, SIC 93120,
    every word of the club's name" is reviewable; a score of 97 is not.
    """
    title = candidate.get("company_name") or candidate.get("title") or ""
    lower = _normalise(title)
    sic = {str(c) for c in (candidate.get("sic_codes") or [])}
    status = (candidate.get("company_status") or "").lower()

    points, why = 0, []

    # Before any points: a different sport is not this club. See
    # ANOTHER_SPORT - SIC 93120 covers every sport, and a rugby club is
    # named a "Rugby Football Club", so without this the two strongest
    # signals both fire for the wrong game.
    if ANOTHER_SPORT.search(lower):
        return 0, ["names a different sport"]

    if SIC_CLUB in sic:
        points += POINTS_SIC_CLUB
        why.append("SIC 93120 (sport club)")
    elif sic & SIC_NEARBY:
        points += POINTS_SIC_NEARBY
        why.append("sport-adjacent SIC " + ",".join(sorted(sic & SIC_NEARBY)))

    if status == "active":
        points += POINTS_ACTIVE
        why.append("active")
    elif status in ("dissolved", "liquidation", "receivership", "converted-closed"):
        points += POINTS_DISSOLVED
        why.append(status)

    if "football club" in lower:
        points += POINTS_FOOTBALL_CLUB
        why.append("named a football club")
    elif re.search(r"\bfc\b", lower):
        points += POINTS_FC
        why.append("named FC")

    if re.search(r"\bholdings?\b", lower):
        points += POINTS_HOLDINGS
        why.append("holding company")

    if NOT_THE_CLUB.search(lower):
        points += POINTS_NOT_THE_CLUB
        why.append("names a body attached to a club, not the club")

    club_tokens = _tokens(club_name)
    company_tokens = set(_tokens(title))

    if known_entity and _legal_tokens(known_entity) == _legal_tokens(title):
        points += POINTS_KNOWN_ENTITY
        why.append("matches the entity these accounts were read from")
    if club_tokens and set(club_tokens) == company_tokens:
        points += POINTS_NAME_EXACT
        why.append("name matches exactly")
    elif club_tokens and set(club_tokens) <= company_tokens:
        points += POINTS_NAME_ALL_TOKENS
        why.append("every word of the club's name")
    else:
        place = _tokens(club_name, drop_club_type=True)
        if place and set(place) <= company_tokens:
            points += POINTS_NAME_PARTIAL
            why.append("the club's place name only")
        else:
            return 0, ["name does not match"]

    # A match on the place name alone, or on a club name that IS a place
    # name, is not evidence of a football club: 74 clubs here are named
    # for one common English word, and "Chelsea Limited" matches "Chelsea"
    # exactly. Something in the name has to say football - unless a person
    # already named this entity, which outranks any inference from it.
    if not FOOTBALL_WORD.search(lower) and "read from" not in " ".join(why):
        if SIC_CLUB in sic or sic & SIC_NEARBY:
            # A sport club named exactly for the place, and nothing says
            # which sport. Worth looking at, not worth choosing.
            points = min(points, MIN_CONFIDENT - 1)
            why.append("nothing in the name says football")
        else:
            return 0, ["nothing in the name says football"]

    return points, why


def candidates_for(directory: Path, club_id: str) -> list[dict]:
    """Every company any query for this club returned, deduped by number."""
    out: dict[str, dict] = {}
    for path in sorted(directory.glob(f"{club_id}__*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("%s is not JSON - skipping", path.name)
            continue
        for item in payload.get("items") or []:
            number = item.get("company_number")
            if not number:
                continue
            # The advanced search carries sic_codes and the plain search
            # does not, so a company found by both keeps the richer copy.
            if number not in out or (item.get("sic_codes")
                                     and not out[number].get("sic_codes")):
                out[number] = item
    return list(out.values())


def rank(club: dict, candidates: list[dict]) -> dict:
    scored = []
    for candidate in candidates:
        points, why = score(club["name"], candidate, club.get("known_entity", ""))
        if points <= 0:
            continue
        scored.append({
            "company_number": candidate.get("company_number"),
            "entity_name": (candidate.get("company_name")
                            or candidate.get("title") or ""),
            "company_status": candidate.get("company_status") or "",
            "sic_codes": ",".join(str(c) for c in (candidate.get("sic_codes") or [])),
            "score": points,
            "why": "; ".join(why),
        })
    scored.sort(key=lambda c: (-c["score"], c["entity_name"]))

    if not scored:
        return {"state": "not_found", "chosen": None, "margin": 0, "runners_up": []}

    best = scored[0]
    margin = best["score"] - (scored[1]["score"] if len(scored) > 1 else best["score"])
    state = "chosen"
    if best["score"] < MIN_CONFIDENT:
        state = "review"
    elif len(scored) > 1 and margin < MIN_MARGIN:
        state = "review"
    return {"state": state, "chosen": best, "margin": margin,
            "runners_up": scored[1:4]}


FIELDS = [
    "club_id", "club_name", "tier", "state", "company_number", "entity_name",
    "company_status", "sic_codes", "score", "margin", "why",
    "known_entity", "known_number", "runners_up",
]


def cmd_targets(args):
    conn = sqlite3.connect(DB)
    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow(["club_id", "club_name", "tier", "queries"])
    rows = targets(conn)
    for club in rows:
        writer.writerow([club["club_id"], club["name"], club["tier"],
                         "|".join(club["queries"])])
    logger.info("%d clubs to look up, %d queries",
                len(rows), sum(len(c["queries"]) for c in rows))


def cmd_score(args):
    conn = sqlite3.connect(DB)
    directory = Path(args.directory)
    rows, counts = [], {"chosen": 0, "review": 0, "not_found": 0}
    agreed = disagreed = 0

    for club in targets(conn):
        result = rank(club, candidates_for(directory, club["club_id"]))
        counts[result["state"]] += 1
        chosen = result["chosen"] or {}

        # The 3 clubs whose company number was recorded by hand are the
        # only ground truth there is. Reported, never overwritten.
        if club["known_number"]:
            if chosen.get("company_number") == club["known_number"]:
                agreed += 1
            else:
                disagreed += 1
                logger.warning(
                    "%s: hand-recorded %s (%s), scorer picked %s (%s)",
                    club["club_id"], club["known_number"], club["known_entity"],
                    chosen.get("company_number"), chosen.get("entity_name"))

        rows.append({
            "club_id": club["club_id"],
            "club_name": club["name"],
            "tier": club["tier"],
            "state": result["state"],
            "company_number": chosen.get("company_number", ""),
            "entity_name": chosen.get("entity_name", ""),
            "company_status": chosen.get("company_status", ""),
            "sic_codes": chosen.get("sic_codes", ""),
            "score": chosen.get("score", ""),
            "margin": result["margin"],
            "why": chosen.get("why", ""),
            "known_entity": club["known_entity"],
            "known_number": club["known_number"],
            "runners_up": json.dumps(result["runners_up"], separators=(",", ":")),
        })

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    logger.info("%d clubs: %d chosen, %d to review, %d not found -> %s",
                len(rows), counts["chosen"], counts["review"],
                counts["not_found"], out)
    if agreed or disagreed:
        logger.info("against the %d hand-recorded company numbers: %d agree, "
                    "%d disagree", agreed + disagreed, agreed, disagreed)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("targets", help="the clubs to look up, as TSV on stdout")
    p.set_defaults(func=cmd_targets)

    p = sub.add_parser("score", help="rank the fetched candidates")
    p.add_argument("directory", help="directory of <club_id>__<n>.json files")
    p.add_argument("-o", "--out", default=str(OUT))
    p.set_defaults(func=cmd_score)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
