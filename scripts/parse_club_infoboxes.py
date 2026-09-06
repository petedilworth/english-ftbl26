#!/usr/bin/env python3
"""
Extract club facts from Wikipedia infoboxes: ground, capacity, colours,
founding year and the ground's coordinates.

WHY BY HAND. Four fields were thin and all four come from outside the
league data. 244 of 356 clubs were missing at least one, capacity worst
of all - only 111 had it, which is why the stadium chart was nearly empty
below the fifth tier. en.wikipedia.org is refused at this environment's
proxy, so the articles are fetched on a machine that can reach them and
handed over, exactly as the tier-6/7 results were.

WHICH COORDINATE. An article can carry several {{coord}} templates, and
the first one is not always the club's ground: Oxford City's article
names two FORMER grounds in prose before the current one. The template
marked `display=title` is the article's own location and the only one
taken; where an article has several and none is marked, none is used.

Measured against the 14 clubs here that already have a surveyed ground
coordinate, that rule lands within a median of 0.3 miles and a worst case
of 1.7. That is the same kind of published error scripts/place_clubs.py
reports for its own method, and it is far inside the 9-mile threshold
that method needs.

WHAT IT REFUSES. A club whose infobox names a different club. Four of
these articles resolved to a renamed or successor side - Farnborough
Town's search landed on Farnborough F.C., Mickleover Sports on Mickleover
F.C. - and a successor's ground is not necessarily the ground of the club
this site records under the older name. Those are reported for a decision
rather than accepted, because a wrong ground is worse than no ground.

    python3 scripts/parse_club_infoboxes.py DIRECTORY [--apply]
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

import entities                                          # noqa: E402
from catchment import great_circle_miles                 # noqa: E402

DB = PROJECT_ROOT / "data" / "db" / "england.db"
CLUB_MASTER = PROJECT_ROOT / "club_master.csv"
CONTENT = PROJECT_ROOT / "content"

logger = logging.getLogger("parse_club_infoboxes")

# England, generously bounded. A coordinate outside this is not a ground
# this site can place - Welsh clubs included, which the catchment model
# already excludes because its gazetteer is English MSOAs.
LAT_RANGE, LON_RANGE = (49.8, 55.9), (-6.5, 2.1)

# A ground holding fewer than a hundred or more than a hundred thousand is
# a parse error, not a stadium.
CAPACITY_RANGE = (100, 100_000)
FOUNDED_RANGE = (1850, 2030)

INFOBOX = re.compile(r"\{\{\s*Infobox football club(.*?)\n\}\}", re.S | re.I)
COORD = re.compile(r"\{\{\s*coord\s*\|([^}]*)\}\}", re.I)


# Wikipedia writes a club's name with its legal suffix; this site does
# not. "Bashley F.C.", "Nuneaton Town FC" and "Guiseley Association
# Football Club" are all the club the site calls by the bare name, and
# comparing them raw reported twenty-one mismatches that were nothing but
# punctuation.
SUFFIX = re.compile(
    r"\s+(?:association\s+)?football\s+club$|\s+A?\.?F\.?C\.?$", re.I)


def _squash(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _same_club(article: str, canonical: str) -> bool:
    """
    Whether an article's club name means the club this site holds.

    Punctuation is not a difference: "A.F.C. Sudbury", "St. Ives Town"
    and "F.C. United of Manchester" are ours. Nor is a formal name that
    extends ours, as "Warrington Rylands 1906" does. A name that is
    neither is a different club, and no amount of similarity makes
    Farnborough F.C. into Farnborough Town.
    """
    a = _squash(SUFFIX.sub("", article).strip())
    c = _squash(SUFFIX.sub("", canonical).strip())
    return bool(a) and (a == c or a.startswith(c))


def _resolve(resolver, name: str) -> str | None:
    if not name:
        return None
    for candidate in (name, SUFFIX.sub("", name).strip()):
        found = resolver.get(entities._normalize(candidate))
        if found:
            return found
    return None


def infobox_fields(text: str) -> dict:
    """The infobox's parameters, as {name: raw value}."""
    m = INFOBOX.search(text)
    if not m:
        return {}
    out, body = {}, m.group(1)
    # Split on newline-pipe so a pipe inside a template or link stays put.
    for chunk in re.split(r"\n\s*\|", body):
        if "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        out[key.strip().lower()] = value.strip()
    return out


def clean(value: str) -> str:
    """Wikitext to plain text: drop refs, comments, templates, links."""
    value = re.sub(r"<ref[^>]*>.*?</ref>", "", value, flags=re.S | re.I)
    value = re.sub(r"<ref[^>]*/>", "", value, flags=re.I)
    value = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    value = re.sub(r"\{\{[^{}]*\}\}", "", value)
    value = re.sub(r"\[\[[^|\]]*\|([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"<[^>]+>", "", value)
    return " ".join(value.split()).strip()


def parse_capacity(raw: str) -> int | None:
    """'2,250 (250 seated)<ref .../>' -> 2250."""
    text = clean(raw)
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d{3,6})", text)
    if not m:
        return None
    value = int(m.group(1).replace(",", ""))
    return value if CAPACITY_RANGE[0] <= value <= CAPACITY_RANGE[1] else None


def parse_founded(raw: str) -> int | None:
    text = clean(raw)
    m = re.search(r"\b(1[89]\d{2}|20[0-2]\d)\b", text)
    if not m:
        return None
    year = int(m.group(1))
    return year if FOUNDED_RANGE[0] <= year <= FOUNDED_RANGE[1] else None


def parse_ground(raw: str) -> str | None:
    """
    'Victory Road, [[Leiston]]' -> 'Victory Road'.

    Some infoboxes list every ground a club has used, unseparated:
    Runcorn's reads "Canal Street (1918-2001)Halton StadiumHaig
    AvenueValerie Park". That is a history, not a ground, and a name
    carrying a year or running past a plausible length is refused rather
    than truncated into something that looks right.
    """
    text = clean(raw)
    if not text:
        return None
    name = text.split(",")[0].strip()
    if not name or len(name) > 50 or re.search(r"\b(1[89]\d{2}|20\d{2})\b", name):
        return None
    return name


def parse_colour(fields: dict) -> str | None:
    """
    The home shirt's body colour. Wikipedia stores it as a bare hex, and
    a named colour or a pattern reference is not one - those are skipped
    rather than guessed at.
    """
    for key in ("body1", "leftarm1"):
        value = clean(fields.get(key, "")).lstrip("#").upper()
        if re.fullmatch(r"[0-9A-F]{6}", value):
            return f"#{value}"
    return None


def _numbers(body: str):
    parts, nums = [p.strip() for p in body.split("|")], []
    for p in parts:
        if re.fullmatch(r"-?\d+(\.\d+)?", p):
            nums.append(float(p))
        elif p.upper() in ("N", "S", "E", "W"):
            nums.append(p.upper())
        else:
            break
    return nums


def parse_one_coord(body: str):
    n = _numbers(body)
    try:
        if len(n) >= 8 and isinstance(n[3], str):
            lat = n[0] + n[1] / 60 + n[2] / 3600
            lon = n[4] + n[5] / 60 + n[6] / 3600
            return (-lat if n[3] == "S" else lat, -lon if n[7] == "W" else lon)
        if len(n) >= 6 and isinstance(n[2], str):
            lat, lon = n[0] + n[1] / 60, n[3] + n[4] / 60
            return (-lat if n[2] == "S" else lat, -lon if n[5] == "W" else lon)
        if len(n) >= 2 and not isinstance(n[1], str):
            return n[0], n[1]
    except (IndexError, TypeError):
        return None
    return None


def parse_coordinates(text: str):
    """
    The article's own location, which is the current ground.

    Not simply the first {{coord}}: Oxford City's article names two
    former grounds in prose before it reaches the present one, and taking
    the first put the club 2.6 miles out. `display=title` marks the
    article's location. Where several exist and none is marked, none is
    taken - a guess between them is not worth a wrong ground.
    """
    found = [(body, parse_one_coord(body)) for body in COORD.findall(text)]
    found = [(b, c) for b, c in found if c]
    for body, coord in found:
        if "display=title" in body.replace(" ", ""):
            return coord
    return found[0][1] if len(found) == 1 else None


def in_england(coord) -> bool:
    lat, lon = coord
    return (LAT_RANGE[0] <= lat <= LAT_RANGE[1]
            and LON_RANGE[0] <= lon <= LON_RANGE[1])


def _apply(proposals: list[dict]) -> None:
    """
    Write the accepted values, and only into blanks.

    Nothing already recorded is overwritten. A ground surveyed for this
    project, or a colour someone chose deliberately, is better evidence
    than an infobox, and a bulk import that silently replaced them would
    be the worst kind of change: invisible and hard to undo.

    Coordinates land in club_master.csv with location_precision='ground',
    which is what the catchment model and the map read. Capacity and
    founding year land in the club's story front-matter, because that is
    where SiteBuilder reads club facts from - a club with no story gets a
    file with facts and no prose, which content/README.md explicitly
    allows.
    """
    rows = list(csv.DictReader(CLUB_MASTER.open(encoding="utf-8")))
    fields = list(rows[0].keys())
    by_id = {r["club_id"]: r for r in rows}
    filled = {"latitude": 0, "stadium_name": 0, "color_primary": 0}

    for p in proposals:
        row = by_id.get(p["club_id"])
        if row is None:
            continue
        if p["lat"] is not None and not (row.get("latitude") or "").strip():
            row["latitude"] = f"{p['lat']:.5f}"
            row["longitude"] = f"{p['lon']:.5f}"
            if "location_precision" in row:
                row["location_precision"] = "ground"
            filled["latitude"] += 1
        if p["ground"] and not (row.get("stadium_name") or "").strip():
            row["stadium_name"] = p["ground"]
            filled["stadium_name"] += 1
        if p["colour"] and not (row.get("color_primary") or "").strip():
            row["color_primary"] = p["colour"]
            filled["color_primary"] += 1

    with CLUB_MASTER.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    for key, n in filled.items():
        print(f"  club_master.csv: filled {n} blank {key}", file=sys.stderr)

    made, merged = 0, 0
    for p in proposals:
        facts = {}
        if p["capacity"]:
            facts["capacity"] = p["capacity"]
        if p["founded"]:
            facts["founded"] = p["founded"]
        if not facts:
            continue
        path = CONTENT / f"{p['club_id']}.md"
        if not path.exists():
            # Front-matter and nothing else. An HTML comment after it
            # counts as prose to content.load_club, which made the page
            # render an invisible comment INSTEAD of the derived summary -
            # 189 club pages went blank where they had a paragraph.
            body = "---\n" + "".join(f"{k}: {v}\n" for k, v in sorted(facts.items()))
            body += "---\n"
            path.write_text(body, encoding="utf-8")
            made += 1
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        head, sep, rest = text[3:].partition("\n---")
        missing = {k: v for k, v in facts.items()
                   if not re.search(rf"^\s*{k}\s*:", head, re.M)}
        if not missing:
            continue
        head = head.rstrip("\n") + "\n" + "".join(
            f"{k}: {v}\n" for k, v in sorted(missing.items()))
        path.write_text("---" + head + sep + rest, encoding="utf-8")
        merged += 1
    print(f"  content/: created {made} fact files, added facts to {merged} existing",
          file=sys.stderr)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="directory of <club_id>.wikitext files")
    parser.add_argument("--apply", action="store_true",
                        help="write into club_master.csv and content/*.md")
    parser.add_argument("--report", default=None,
                        help="write the full proposal here as TSV")
    args = parser.parse_args()

    files = sorted(Path(args.directory).glob("*.wikitext"))
    if not files:
        sys.exit(f"no .wikitext files in {args.directory}")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    resolver = entities.build_resolver(conn)
    master = {r["club_id"]: r for r in conn.execute(
        "SELECT club_id, canonical_name, latitude, longitude, stadium_name,"
        " color_primary, location_precision FROM club_master")}
    msoas = conn.execute(
        "SELECT latitude, longitude FROM msoa_demographics").fetchall()

    proposals, mismatched, unplaceable, renamed_clubs = [], [], [], []
    for path in files:
        club_id = path.stem
        row = master.get(club_id)
        if row is None:
            mismatched.append((club_id, "not in club_master", ""))
            continue

        text = path.read_text(encoding="utf-8", errors="replace")
        fields = infobox_fields(text)
        if not fields:
            mismatched.append((club_id, "no infobox", ""))
            continue

        # The identity check. An article reached by search can be a
        # renamed or successor club, whose ground is not necessarily the
        # ground of the club this site holds under the older name.
        article_name = clean(fields.get("clubname") or fields.get("fullname") or "")
        resolved = _resolve(resolver, article_name)
        # Two different problems, and only one is caught by resolving.
        # An article that resolves to nobody is plainly a different club.
        # An article that resolves to THIS club but under a different name
        # is a rename or a successor - "Farnborough" resolves to
        # Farnborough Town because the site holds it as a variant, but
        # Farnborough F.C. is the club that replaced them, and its ground
        # need not be theirs. Both are reported; neither is guessed at.
        canonical = row["canonical_name"]
        stripped = SUFFIX.sub("", article_name).strip()
        accept = True
        if resolved != club_id:
            mismatched.append((club_id, article_name or "(no name)",
                               resolved or "unresolved"))
            accept = False
        elif not _same_club(stripped, canonical):
            # Mechanical, not a judgement about football history: the name
            # matches after punctuation, or it extends ours ("Warrington
            # Rylands 1906"), or it does not and the club is left alone.
            # "Leamington" is not "AP Leamington" and "Farnborough" is not
            # "Farnborough Town" - those are the clubs that REPLACED them,
            # and a successor's ground is not the ground this site means.
            renamed_clubs.append((club_id, canonical, article_name))
            accept = False

        coord = parse_coordinates(text)
        if coord and not in_england(coord):
            unplaceable.append((club_id, f"{coord[0]:.4f},{coord[1]:.4f}",
                                "outside England"))
            coord = None
        if coord:
            nearest = min(great_circle_miles(coord[0], coord[1], m[0], m[1])
                          for m in msoas)
            if nearest > 5.0:
                unplaceable.append((club_id, f"{coord[0]:.4f},{coord[1]:.4f}",
                                    f"{nearest:.1f} mi from any populated area"))
                coord = None

        if not accept:
            continue
        proposals.append({
            "club_id": club_id,
            "article_name": article_name,
            "identity_ok": resolved == club_id,
            "ground": parse_ground(fields.get("ground", "")),
            "capacity": parse_capacity(fields.get("capacity", "")),
            "founded": parse_founded(fields.get("founded", "")),
            "colour": parse_colour(fields),
            "lat": round(coord[0], 5) if coord else None,
            "lon": round(coord[1], 5) if coord else None,
            "has_ground": bool((row["stadium_name"] or "").strip()),
            "has_colour": bool((row["color_primary"] or "").strip()),
            "has_coord": row["latitude"] is not None,
        })

    def new(field, have):
        return sum(1 for p in proposals if p[field] and not p[have])

    print(f"\nparsed {len(proposals)} of {len(files)} files", file=sys.stderr)
    print(f"  ground     {sum(1 for p in proposals if p['ground']):>4} found,"
          f" {new('ground','has_ground'):>4} new", file=sys.stderr)
    print(f"  capacity   {sum(1 for p in proposals if p['capacity']):>4} found",
          file=sys.stderr)
    print(f"  founded    {sum(1 for p in proposals if p['founded']):>4} found",
          file=sys.stderr)
    print(f"  colours    {sum(1 for p in proposals if p['colour']):>4} found,"
          f" {new('colour','has_colour'):>4} new", file=sys.stderr)
    print(f"  coordinate {sum(1 for p in proposals if p['lat']):>4} found,"
          f" {new('lat','has_coord'):>4} new", file=sys.stderr)
    print(f"\n  identity mismatches: {len(mismatched)}", file=sys.stderr)
    for club_id, article, resolved in mismatched:
        print(f"     {club_id:32} infobox says {article!r} -> {resolved}",
              file=sys.stderr)
    print(f"\n  article names a renamed or successor club: {len(renamed_clubs)}",
          file=sys.stderr)
    for club_id, canonical, article in renamed_clubs:
        print(f"     {club_id:32} we say {canonical!r}, article says {article!r}",
              file=sys.stderr)
    print(f"\n  coordinates refused: {len(unplaceable)}", file=sys.stderr)
    for club_id, coord, why in unplaceable:
        print(f"     {club_id:32} {coord} {why}", file=sys.stderr)

    if args.apply:
        _apply(proposals)

    if args.report:
        with open(args.report, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(proposals[0].keys()),
                               delimiter="\t")
            w.writeheader()
            w.writerows(proposals)
        print(f"\nwrote {args.report}", file=sys.stderr)


if __name__ == "__main__":
    main()
