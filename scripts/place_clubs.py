#!/usr/bin/env python3
"""
Place a non-league club on the map from the ONS data already in the repo.

WHY THIS EXISTS. The catchment model needs a coordinate for every club
that competes for people, including the sixth- and seventh-tier clubs that
have no league history here. Published ground coordinates for those clubs
are not reachable from this environment - the hosts that carry them are
refused at the network proxy - so the roster places a club at the
population-weighted centroid of its local authority, taken from
msoa_demographics.csv, and records location_precision = 'town'.

HOW GOOD IS THAT. Measured, not asserted. `validate` places the clubs
that DO have a surveyed ground coordinate by this same method and reports
the error by how widely their authority's population is spread:

    spread  0-4 mi   n= 86   median 1.4   p90  2.8   max  3.7
    spread  4-6 mi   n= 32   median 2.0   p90  2.9   max  4.4
    spread  6-9 mi   n= 20   median 2.4   p90  6.8   max  8.0
    spread  9+ mi    n= 23   median 9.8   p90 16.9   max 35.7

The cliff is at nine miles, and everything past it is a large rural
authority - Cornwall, Somerset, Cumberland, North Yorkshire - whose
centroid is near no particular town at all. Below it the worst case is
Guiseley at 8.0 miles: a club in a big city's authority but out at the
edge of it, which is the failure mode that remains.

So the rule is a threshold on the authority rather than a judgement about
the club. Past MAX_SPREAD_MILES the club is reported unplaced rather than
put in the wrong town. The threshold is set where it is because BOTH
errors are real: a club the model cannot see has its town handed to its
neighbours, which is the bug this whole layer exists to fix, so excluding
a club is not the safe option it looks like.

CLUBS OUTSIDE ENGLAND CANNOT BE PLACED AT ALL. The gazetteer is English
MSOAs, so Merthyr Town has no authority to sit in. They are reported, not
guessed - and they are easy to spot, because every English ground is
within 1.5 miles of an MSOA centroid while the Welsh ones are 9 to 31.

    python3 scripts/place_clubs.py --validate
    python3 scripts/place_clubs.py --authorities 6
    python3 scripts/place_clubs.py --place clubs.tsv > rows.csv

The --place input is tab-separated, one club per line:

    canonical_name <TAB> local_authority <TAB> tier <TAB> division <TAB> ground_name
"""

import argparse
import csv
import math
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import roster  # noqa: E402
from catchment import great_circle_miles  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MSOA_CSV = PROJECT_ROOT / "msoa_demographics.csv"
DB = PROJECT_ROOT / "data" / "db" / "england.db"

# An authority wider than this cannot stand in for one of its towns. Set
# from the validation above: below it the worst observed error is 8.0
# miles and the median 1.6, above it the median alone is 9.8.
MAX_SPREAD_MILES = 9.0

# A ground further than this from any MSOA centroid is not in England, so
# the gazetteer cannot place it and it must not appear in the validation
# either. English grounds are all within 1.5 miles; the Welsh ones are 8.8
# and up, so nothing sits near this line.
OUTSIDE_GAZETTEER_MILES = 5.0

SOURCE_URL = ("https://www.ons.gov.uk/peoplepopulationandcommunity/"
              "populationandmigration/populationestimates")


def load_msoas():
    rows = []
    with MSOA_CSV.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            rows.append((float(r["latitude"]), float(r["longitude"]),
                         int(r["population"]), r["local_authority"]))
    return rows


def authorities(msoas):
    """
    Each authority's population-weighted centroid, and the radius holding
    90% of its people - the number that decides whether it can place a
    club at all.
    """
    grouped = defaultdict(list)
    for lat, lon, pop, la in msoas:
        grouped[la].append((lat, lon, pop))

    out = {}
    for la, rows in grouped.items():
        total = sum(p for _, _, p in rows)
        clat = sum(a * p for a, _, p in rows) / total
        clon = sum(b * p for _, b, p in rows) / total
        ordered = sorted((great_circle_miles(clat, clon, a, b), p)
                         for a, b, p in rows)
        run, spread = 0, ordered[-1][0]
        for d, p in ordered:
            run += p
            if run >= 0.9 * total:
                spread = d
                break
        out[la] = {"lat": clat, "lon": clon, "spread": spread,
                   "population": total, "msoas": len(rows)}
    return out


def cmd_authorities(args):
    las = authorities(load_msoas())
    usable = {k: v for k, v in las.items() if v["spread"] <= args.max_spread}
    print(f"{len(usable)} of {len(las)} authorities are within "
          f"{args.max_spread} miles and can place a club\n")
    for la, v in sorted(las.items(), key=lambda kv: kv[1]["spread"]):
        mark = " " if v["spread"] <= args.max_spread else "X"
        print(f"{mark} {v['spread']:5.1f}  {la:38} {v['population']:>9,} "
              f"{v['lat']:.5f},{v['lon']:.5f}")


def cmd_validate(args):
    """
    Place the clubs that already have surveyed grounds by this method,
    and report how far off it puts them. The honest way to publish a
    guess is with its measured error attached.
    """
    if not DB.exists():
        sys.exit("no database - run the pipeline first")
    msoas = load_msoas()
    las = authorities(msoas)
    conn = sqlite3.connect(DB)

    errors, foreign = [], []
    for cid, lat, lon in conn.execute(
            "SELECT club_id, latitude, longitude FROM club_master"
            " WHERE latitude IS NOT NULL"):
        # Which authority is this ground in? Nearest MSOA centroid, which
        # is exact enough for the assignment even where it is not exact
        # enough for the placement.
        nearest = min(msoas, key=lambda m: great_circle_miles(lat, lon, m[0], m[1]))
        if great_circle_miles(lat, lon, nearest[0], nearest[1]) > OUTSIDE_GAZETTEER_MILES:
            # Not in England. Including it would measure the width of the
            # Bristol Channel rather than the accuracy of the method.
            foreign.append(cid)
            continue
        cell = las[nearest[3]]
        errors.append((great_circle_miles(lat, lon, cell["lat"], cell["lon"]),
                       cell["spread"], cid, nearest[3]))
    errors.sort()

    def report(label, rows):
        if not rows:
            return
        es = sorted(e for e, *_ in rows)
        print(f"{label:38} n={len(es):4}  median {statistics.median(es):5.1f}"
              f"  p90 {es[int(0.9 * (len(es) - 1))]:5.1f}  max {max(es):5.1f}")

    print("Error of the town-centroid placement against the real ground, miles\n")
    report("all English clubs with a ground", errors)
    report(f"authority spread <= {MAX_SPREAD_MILES} mi (placeable)",
           [e for e in errors if e[1] <= MAX_SPREAD_MILES])
    report(f"authority spread > {MAX_SPREAD_MILES} mi (refused)",
           [e for e in errors if e[1] > MAX_SPREAD_MILES])
    print()
    for lo, hi in [(0, 4), (4, 6), (6, 9), (9, 999)]:
        report(f"  spread {lo}-{hi} mi", [e for e in errors if lo <= e[1] < hi])
    if foreign:
        print(f"\nnot in the gazetteer, excluded: {', '.join(sorted(foreign))}")

    print("\nworst placements, all of them in authorities the threshold excludes:")
    for e, spread, cid, la in errors[-10:]:
        flag = "excluded" if spread > MAX_SPREAD_MILES else "ALLOWED"
        print(f"  {e:5.1f} mi  spread {spread:5.1f}  {flag:8}  {cid:32} {la}")


def cmd_place(args):
    """
    Turn a tab-separated club list into roster rows, refusing any club
    whose authority is too wide to stand in for its town.
    """
    las = authorities(load_msoas())
    master = set()
    if DB.exists():
        master = {r[0] for r in sqlite3.connect(DB).execute(
            "SELECT club_id FROM club_master")}

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(roster.ROSTER_COLUMNS)
    unplaced = []

    with Path(args.file).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = (line.split("\t") + [""] * 5)[:5]
            name, la, tier, division, ground = (p.strip() for p in parts)

            cell = las.get(la)
            if cell is None:
                unplaced.append((name, f"no such authority: {la!r}"))
                continue
            if cell["spread"] > MAX_SPREAD_MILES:
                unplaced.append(
                    (name, f"{la} spreads {cell['spread']:.1f} mi - too wide to"
                           " stand in for one town"))
                continue

            club_id = f"{roster.slugify(name)}-fc"
            if club_id in master:
                unplaced.append((name, "already in club_master"))
                continue

            writer.writerow([
                club_id, name, tier, division, ground,
                f"{cell['lat']:.4f}", f"{cell['lon']:.4f}", "town", la,
                SOURCE_URL,
                f"population-weighted centroid of {la}, whose population"
                f" spreads {cell['spread']:.1f} mi",
            ])

    for name, why in unplaced:
        print(f"# UNPLACED {name}: {why}", file=sys.stderr)
    if unplaced:
        print(f"# {len(unplaced)} club(s) unplaced", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("authorities", help="list authorities and their spread")
    p.add_argument("max_spread", nargs="?", type=float, default=MAX_SPREAD_MILES)
    p.set_defaults(func=cmd_authorities)

    p = sub.add_parser("validate", help="measure this method against real grounds")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("place", help="turn a club list into roster rows")
    p.add_argument("file")
    p.set_defaults(func=cmd_place)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
