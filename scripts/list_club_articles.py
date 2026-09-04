#!/usr/bin/env python3
"""
List the clubs whose facts are missing, with candidate Wikipedia titles.

WHY THIS EXISTS. Four fields are thin and all four come from outside the
league data: a club's ground, its capacity, its colours and its
coordinates. Capacity feeds the stadium chart, which is why that chart is
almost empty below the fifth tier; coordinates feed the catchment model,
which is why twenty clubs still playing are invisible to it. None of them
can be reached from this environment - en.wikipedia.org is refused at the
proxy - so the articles are fetched on a machine that can reach them,
exactly as the tier-6/7 results were.

WHY CANDIDATE TITLES RATHER THAN ONE. English club articles are not
titled consistently: "Leiston F.C.", but "AFC Totton" with no full stops,
and "Rushden & Diamonds A.F.C." rather than "AFC Rushden & Diamonds".
Guessing one title wrongly loses a club silently, so each row carries
several in the order most likely to be right, and the fetch keeps the
first that is actually a club article.

The output is committed rather than generated on the user's machine so
the list is reviewable, and so the fetch script can be short enough to
paste.

    python3 scripts/list_club_articles.py
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB = PROJECT_ROOT / "data" / "db" / "england.db"
CONTENT = PROJECT_ROOT / "content"
OUT = PROJECT_ROOT / "data" / "wikipedia-club-articles.tsv"

# Capacity lives in a club story's front-matter rather than in the
# database, which is why it is read from disk here.
CAPACITY_RE = re.compile(r"^\s*capacity\s*:\s*\d", re.M)


def clubs_with_a_capacity() -> set[str]:
    return {
        path.stem for path in CONTENT.glob("*.md")
        if CAPACITY_RE.search(path.read_text(encoding="utf-8", errors="replace")[:2500])
    }


def candidate_titles(name: str) -> list[str]:
    """
    Article titles to try, most likely first.

    "AFC Totton" is titled exactly that; "AFC Rushden & Diamonds" is at
    "Rushden & Diamonds A.F.C."; everything else is usually "<name> F.C."
    with the bare name as a fallback for clubs whose article has no suffix.
    """
    name = name.strip()
    if name.startswith("AFC "):
        rest = name[4:]
        out = [name, f"A.F.C. {rest}", f"{rest} A.F.C.", f"{rest} F.C."]
    elif name.endswith((" FC", " AFC")):
        # "Wimbledon FC" is the article; "Wimbledon FC F.C." is nothing.
        stem = name.rsplit(" ", 1)[0]
        out = [name, f"{stem} F.C.", f"{stem} A.F.C.", stem]
    else:
        out = [f"{name} F.C.", name, f"{name} A.F.C."]
    seen, unique = set(), []
    for title in out:
        if title not in seen:
            seen.add(title)
            unique.append(title)
    return unique[:4]


def missing_fields(row, has_capacity: set[str]) -> list[str]:
    missing = []
    if not row["latitude"]:
        missing.append("coords")
    if not (row["stadium_name"] or "").strip():
        missing.append("ground")
    if not (row["color_primary"] or "").strip():
        missing.append("colours")
    if row["club_id"] not in has_capacity:
        missing.append("capacity")
    return missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--out", default=str(OUT))
    args = parser.parse_args()

    if not DB.exists():
        sys.exit(f"no database at {DB}")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    has_capacity = clubs_with_a_capacity()

    rows = conn.execute(
        "SELECT club_id, canonical_name, latitude, stadium_name, color_primary"
        " FROM club_master ORDER BY canonical_name").fetchall()

    lines = []
    for row in rows:
        missing = missing_fields(row, has_capacity)
        if not missing:
            continue
        lines.append("\t".join(
            [row["club_id"], ",".join(missing)]
            + candidate_titles(row["canonical_name"])))

    out_path = Path(args.out)
    with out_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Clubs whose ground, capacity, colours or coordinates are not\n")
        fh.write("# recorded here, with candidate Wikipedia article titles. Generated\n")
        fh.write("# by scripts/list_club_articles.py; the fetch tries each title in\n")
        fh.write("# order and keeps the first that is a club article.\n")
        fh.write("club_id\tmissing\tcandidate_titles...\n")
        fh.write("\n".join(lines) + "\n")

    print(f"{len(lines)} clubs of {len(rows)} need at least one field",
          file=sys.stderr)
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
