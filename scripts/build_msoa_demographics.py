"""
Build msoa_demographics.csv from three ONS downloads.

Run once, by hand, when the source files are refreshed. The inputs cannot
be fetched from this environment - ons.gov.uk and the Open Geography
Portal are refused at the proxy - so they are downloaded manually and
passed in as paths. See docs/catchment-data.md.

Sources:
  centroids  MSOA (Dec 2021) EW Population Weighted Centroids, BNG
  population Mid-year MSOA population estimates by single year of age
  income     Small area income estimates, net annual household income

Usage:
  python3 scripts/build_msoa_demographics.py CENTROIDS.csv POP.xlsx INCOME.xlsx \
      [--check WGS84_LATLONG.csv] [-o msoa_demographics.csv]
"""

import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bng import bng_to_wgs84

HEADER = [
    "msoa_code", "msoa_name", "local_authority", "latitude", "longitude",
    "population", "population_year", "net_income", "net_income_year",
    "income_ci_lower", "income_ci_upper", "source_url",
]
SOURCE = "https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/populationestimates"


def read_centroids(path):
    """MSOA code -> (lat, lon), converted from British National Grid."""
    out = {}
    with open(path, encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("MSOA21CD") or "").strip()
            if not code.startswith("E02"):        # England only
                continue
            out[code] = bng_to_wgs84(float(row["X"]), float(row["Y"]))
    return out


def read_sheet(path, sheet, header_row=4):
    """ONS spreadsheets carry three lines of preamble above the header."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet]
    rows = ws.iter_rows(min_row=header_row, values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(rows)]
    out = [dict(zip(header, r)) for r in rows]
    wb.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("centroids"); ap.add_argument("population"); ap.add_argument("income")
    ap.add_argument("--pop-sheet", default="Mid-2024 MSOA 2021")
    ap.add_argument("--pop-year", type=int, default=2024)
    ap.add_argument("--income-sheet", default="Net annual income")
    ap.add_argument("--income-year", type=int, default=2023)
    ap.add_argument("--check", help="independent WGS84 lat/long CSV to validate against")
    ap.add_argument("-o", "--out", default="msoa_demographics.csv")
    args = ap.parse_args()

    centroids = read_centroids(args.centroids)
    print(f"centroids: {len(centroids)} English MSOAs")

    pop = {}
    for r in read_sheet(args.population, args.pop_sheet):
        code = str(r.get("MSOA 2021 Code") or "").strip()
        if code.startswith("E02"):
            pop[code] = (r.get("MSOA 2021 Name"), r.get("LAD 2023 Name"), r.get("Total"))
    print(f"population: {len(pop)} rows from {args.pop_sheet!r}")

    inc = {}
    for r in read_sheet(args.income, args.income_sheet):
        code = str(r.get("MSOA code") or "").strip()
        if code.startswith("E02"):
            inc[code] = (r.get("Disposable (net) annual income (£)"),
                         r.get("Lower confidence limit (£)"),
                         r.get("Upper confidence limit (£)"))
    print(f"income: {len(inc)} rows from {args.income_sheet!r}")

    # Validate the datum conversion against an independent WGS84 source.
    # A wrong Helmert transform is off by hundreds of miles, not metres;
    # genuine disagreement here is the population-weighted vs geometric
    # centroid difference, which is small.
    if args.check:
        with open(args.check, encoding="utf-8-sig") as fh:
            other = {r["MSOACD"].strip(): (float(r["latitude"]), float(r["longitude"]))
                     for r in csv.DictReader(fh) if r["MSOACD"].strip().startswith("E02")}
        gaps = []
        for code, (lat, lon) in centroids.items():
            if code in other:
                la2, lo2 = other[code]
                dlat = (lat - la2) * 69.0
                dlon = (lon - lo2) * 69.0 * math.cos(math.radians(lat))
                gaps.append(math.hypot(dlat, dlon))
        gaps.sort()
        print(f"datum check against {len(gaps)} shared MSOAs: "
              f"median {gaps[len(gaps)//2]:.2f} mi, "
              f"p95 {gaps[int(len(gaps)*0.95)]:.2f} mi, max {gaps[-1]:.2f} mi")
        if gaps[len(gaps)//2] > 5:
            sys.exit("FAILED: median offset over 5 miles - the conversion is wrong")

    rows, skipped = [], 0
    for code, (lat, lon) in sorted(centroids.items()):
        if code not in pop:
            skipped += 1
            continue
        name, la, total = pop[code]
        income, lower, upper = inc.get(code, (None, None, None))
        rows.append([
            code, name, la, f"{lat:.6f}", f"{lon:.6f}", total, args.pop_year,
            income or "", args.income_year if income else "",
            lower or "", upper or "", SOURCE,
        ])

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(rows)

    have_income = sum(1 for r in rows if r[7] != "")
    print(f"\nwrote {args.out}: {len(rows)} rows "
          f"({skipped} centroids had no population match)")
    print(f"  with income: {have_income}")
    print(f"  total population: {sum(int(r[5]) for r in rows if r[5]):,}")


if __name__ == "__main__":
    main()
