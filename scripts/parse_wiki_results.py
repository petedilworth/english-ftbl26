#!/usr/bin/env python3
"""
Extract sixth- and seventh-tier results from Wikipedia season articles.

WHY BY HAND. engsoccerdata stopped updating its non-league sets after
2018/19 and nothing below the fifth tier exists on a host this environment
can reach - openfootball, its mirror footballcsv, worldfootballR and
jfjelstul all stop at tier 5, and en.wikipedia.org is refused at the
proxy. So the articles are fetched on a machine that can reach them and
the wikitext is handed over. Only the results extracted here are
committed; the article text is not, and is not needed again.

WHAT THE SOURCE IS. Each season article carries, per division, a results
grid built with the `sports results` Lua module:

    |team_order=ALF, BAN, BIS, ...
    |name_ALF= [[Alfreton Town F.C.|Alfreton Town]]
    |match_ALF_BAN=2-0 |match_ALF_BIS=3-0 ...

The key names the home club and then the away one, so no fixture has to
be inferred from a date or a position in a table. That is why this is
worth more than transcribing the published league tables: every table the
site shows below the fifth tier is still computed from results by its own
points rule, exactly as tiers 1 to 5 are.

WHAT IT DOES NOT CARRY. Dates. `match_date` is nullable throughout
(aggregate.py writes None when a file has no parseable dates, and
digest.py guards on IS NOT NULL), so these seasons simply have no
date-derived features.

    python3 scripts/parse_wiki_results.py DIRECTORY_OF_WIKITEXT
"""

import argparse
import csv
import logging
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import divisions                                        # noqa: E402
import entities                                         # noqa: E402
import historical                                       # noqa: E402

# NOT data/raw/, which is gitignored: that directory holds files the
# pipeline can fetch again, and these it cannot.
OUT_DIR = PROJECT_ROOT / "data" / "nonleague"
DB = PROJECT_ROOT / "data" / "db" / "england.db"

logger = logging.getLogger("parse_wiki_results")

# Which level-2 section of which article is a division this site models.
# The same articles also carry the divisions BELOW these - the Isthmian
# North, the Southern Division One, and so on - which are the eighth tier
# and must not be picked up, so this is a whitelist rather than a filter.
DIVISION_SECTIONS = {
    ("National_League", "National League North"): "national-league-north",
    ("National_League", "National League South"): "national-league-south",
    ("Isthmian_League", "Premier Division"): "isthmian-league-premier",
    ("Northern_Premier_League", "Premier Division"):
        "northern-premier-league-premier",
    ("Southern_Football_League", "Premier Division Central"):
        "southern-league-premier-central",
    ("Southern_Football_League", "Premier Division South"):
        "southern-league-premier-south",
}

# A club code is short and mostly letters, but not always only letters:
# Wingate & Finchley are W&F.
CODE = r"[A-Za-z0-9&'’.\-]{1,8}"

# Level 2 ONLY. Without the lookarounds this also matches "=== Results
# table ===", which truncates every section at its first subsection and
# yields a grid with no matches in it at all.
SECTION_2 = re.compile(r"^==(?!=)\s*(.+?)\s*(?<!=)==\s*$", re.M)
SECTION_3 = re.compile(r"^===(?!=)\s*(.+?)\s*(?<!=)===\s*$", re.M)

# Four different dashes separate the two scores across these articles:
# hyphen, en-dash, em-dash and the true minus sign. Matching only the
# hyphen loses about ten thousand results without erroring.
SCORE = re.compile(rf"\|\s*match_({CODE})_({CODE})\s*=\s*(\d+)\s*[-–—−]\s*(\d+)")
# A cell holding H/W or A/W is a match awarded rather than played.
AWARDED = re.compile(rf"\|\s*match_({CODE})_({CODE})\s*=\s*([HA])/W\b")
NAME = re.compile(rf"\|\s*name_({CODE})\s*=\s*(.+)")
TEAM_ORDER = re.compile(r"\|\s*team_order\s*=\s*([^\n]+)")
TEAM_N = re.compile(rf"\|\s*team\d+\s*=\s*({CODE})")


def _display_name(raw: str) -> str:
    """The club's name out of a wikitext cell: [[Foo F.C.|Foo]] -> Foo."""
    raw = re.sub(r"<!--.*?-->", "", raw)
    raw = re.sub(r"\{\{\s*nowrap\s*\|(.*?)\}\}", r"\1", raw)
    piped = re.search(r"\[\[[^|\]]*\|([^\]]+)\]\]", raw)
    plain = re.search(r"\[\[([^\]|]+)\]\]", raw)
    text = piped.group(1) if piped else (plain.group(1) if plain else raw)
    return text.strip().strip("}").strip()


def _results_body(section: str) -> str | None:
    """
    The results-grid subsection of a division's section.

    Scoped deliberately: the league-table template above it declares
    name_XXX for every club too, so reading names from the whole section
    reports a 22-club division as having 44 clubs.
    """
    parts = SECTION_3.split(section)
    for i in range(1, len(parts), 2):
        if parts[i].strip().lower().startswith("results"):
            return parts[i + 1]
    return None


def _grid_clubs(body: str) -> list[str]:
    """
    The codes the GRID itself lists, in order.

    This is the club list that counts, and it is not always the league
    table's. Marske United resigned from the Northern Premier League in
    January 2024 and their record was expunged, so 2023/24 is a 21-club
    season under a 22-row table; the grid says 21 and is right. Reading
    the table instead would mark three complete seasons as short.
    """
    order = TEAM_ORDER.search(body)
    if order:
        return [c.strip() for c in order.group(1).split(",") if c.strip()]
    return TEAM_N.findall(body)          # the |team1=|team2= spelling


def parse_file(path: Path) -> dict[tuple[int, str], dict]:
    """One wikitext article to {(season, division_id): {...}}."""
    league = path.stem.split("_", 1)[1]
    season_end_year = int(path.stem[:4]) + 1
    text = path.read_text(encoding="utf-8")

    out = {}
    parts = SECTION_2.split(text)
    for i in range(1, len(parts), 2):
        heading, section = parts[i], parts[i + 1]
        division_id = DIVISION_SECTIONS.get((league, heading))
        if division_id is None:
            continue

        body = _results_body(section)
        if body is None:
            logger.warning("%s / %s has no results subsection",
                           path.name, heading)
            continue

        names = {code: _display_name(raw) for code, raw in NAME.findall(body)}
        codes = _grid_clubs(body)
        rows, awarded = [], []
        for home, away, hg, ag in SCORE.findall(body):
            rows.append((home, away, int(hg), int(ag)))
        for home, away, who in AWARDED.findall(body):
            # Points come from FTR and goals from FTHG/FTAG separately
            # (aggregate.py), so an awarded match can carry the right
            # result with a nominal score. The table is exact; the goal
            # difference is understated by this one match.
            awarded.append((home, away, who))
            rows.append((home, away, 1, 0) if who == "H" else (home, away, 0, 1))

        out[(season_end_year, division_id)] = {
            "codes": codes, "names": names, "rows": rows, "awarded": awarded,
        }
    return out


def _resolve(names: dict[str, str], conn) -> tuple[dict[str, str], list[str]]:
    resolver = entities.build_resolver(conn)
    resolved, missing = {}, []
    for code, name in names.items():
        club_id = resolver.get(entities._normalize(name))
        if club_id is None:
            missing.append(name)
        resolved[code] = name
    return resolved, missing


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="directory of .wikitext articles")
    parser.add_argument("-o", "--out", default=str(OUT_DIR))
    parser.add_argument("--allow-unresolved", action="store_true",
                        help="report unknown club names instead of failing")
    args = parser.parse_args()

    files = sorted(Path(args.directory).glob("*.wikitext"))
    if not files:
        sys.exit(f"no .wikitext files in {args.directory}")

    grids: dict[tuple[int, str], dict] = {}
    for path in files:
        grids.update(parse_file(path))

    conn = sqlite3.connect(DB)
    all_names = {}
    for g in grids.values():
        all_names.update(g["names"])
    _, missing = _resolve(all_names, conn)
    if missing:
        logger.error("%d club name(s) this project cannot resolve:", len(missing))
        for name in sorted(set(missing)):
            logger.error("    %s", name)
        if not args.allow_unresolved:
            sys.exit("add them to club_master.csv - a guessed identity is worse "
                     "than a failed run")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    short, total = [], 0
    for (season, division_id), g in sorted(grids.items()):
        codes, names, rows = g["codes"], g["names"], g["rows"]
        expected = len(codes) * (len(codes) - 1)
        total += len(rows)
        label = f"{season - 1}/{season % 100:02d} {division_id}"
        if len(rows) != expected:
            short.append((label, len(rows), expected))
        for home, away, who in g["awarded"]:
            logger.info("%s: %s v %s awarded (%s) - recorded as a %s win with a "
                        "nominal score", label, names.get(home, home),
                        names.get(away, away), f"{who}/W",
                        "home" if who == "H" else "away")

        path = out_dir / historical.nonleague_filename(season, division_id)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Div", "Date", "HomeTeam", "AwayTeam",
                             "FTHG", "FTAG", "FTR"])
            for home, away, hg, ag in rows:
                writer.writerow([
                    division_id, "", names.get(home, home), names.get(away, away),
                    hg, ag, "H" if hg > ag else "A" if ag > hg else "D",
                ])

    for label, got, expected in short:
        logger.warning("%s: %d of %d matches - part-played or curtailed",
                       label, got, expected)
    logger.info("Wrote %d division-seasons, %d matches, to %s",
                len(grids), total, out_dir)

    # The counts are the quality control. Every trap in this format is
    # silent - a missed dash, a section split that eats the body, a club
    # list read from the wrong template - and each one shows up here as a
    # division-season that is not a round-robin rather than as an error.
    if len(grids) != 40:
        sys.exit(f"expected 40 division-seasons, parsed {len(grids)}")
    if len(short) > 11:
        sys.exit(f"{len(short)} division-seasons are not round-robins; 11 are "
                 "known (COVID 2019/20 and 2020/21, the in-progress season, "
                 "and two awarded matches)")


if __name__ == "__main__":
    main()
