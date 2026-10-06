"""
Fetch the English Indices of Deprivation 2025 and roll them up from small
areas (LSOAs) to the neighbourhoods (MSOAs) the catchment model uses.

Runs in GitHub Actions (.github/workflows/deprivation.yml): the hosts are
not reachable from every development sandbox. Writes two small files the
site reads at build time, and nothing else:

  data/msoa_deprivation.csv        one row per 2021 MSOA in England
  data/msoa_deprivation.meta.json  where it came from, and how it was joined

Sources (both Open Government Licence v3):
  - MHCLG, English Indices of Deprivation 2025, File 7: every score, rank
    and decile, and the population denominators, for each 2021 LSOA.
  - ONS Open Geography Portal: the 2021 LSOA to MSOA lookup. Found through
    the ArcGIS search API, since the portal has no stable download URL.
    If that fails, the join falls back to the ONS naming rule - a 2021 LSOA
    is named for its MSOA plus a letter ("Bolton 012C" is in "Bolton 012") -
    which is exact for every LSOA in England, and the meta file says which
    join was used.

Scores are averaged over each MSOA's LSOAs, weighted by population: that
is the standard way to aggregate IoD scores to a larger area. The
neighbourhood rank is recomputed over the 6,856 MSOAs, 1 the most deprived.
"""

import argparse
import datetime
import io
import json
import re
import sys
from pathlib import Path

import pandas as pd
import requests

FILE_7_URLS = [
    # The re-issued file first, then the October 2025 original.
    "https://assets.publishing.service.gov.uk/media/691ded56d140bbbaa59a2a7d/"
    "File_7_IoD2025_All_Ranks_Scores_Deciles_Population_Denominators.csv",
    "https://assets.publishing.service.gov.uk/media/68ff5daabcb10f6bf9bef911/"
    "File_7_IoD2025_All_Ranks_Scores_Deciles_Population_Denominators.csv",
]
ARCGIS_SEARCH = "https://www.arcgis.com/sharing/rest/search"

# Stored name -> a pattern that picks the score column out of File 7's header.
DOMAINS = {
    "imd": r"^index of multiple deprivation \(imd\) score",
    "income": r"^income score",
    "employment": r"^employment score",
    "education": r"^education, skills and training score",
    "health": r"^health deprivation and disability score",
    "crime": r"^crime score",
    "housing": r"^barriers to housing and services score",
    "environment": r"^living environment score",
    "idaci": r"^income deprivation affecting children index \(idaci\) score",
    "idaopi": r"^income deprivation affecting older people( index)? \(idaopi\) score",
}
MIN_MSOAS = 6_800


def find_columns(columns) -> dict:
    """Map File 7's long headers to short names. Raises with the header on a miss."""
    low = {c: c.strip().lower() for c in columns}
    out = {}
    for key, pat in {"lsoa_code": r"^lsoa code", "lsoa_name": r"^lsoa name",
                     "population": r"^total population"}.items():
        hits = [c for c, l in low.items() if re.search(pat, l)]
        if hits:
            out[key] = hits[0]
    for key, pat in DOMAINS.items():
        hits = [c for c, l in low.items() if re.search(pat, l)]
        if hits:
            out[key] = hits[0]
    missing = {"lsoa_code", "population", "imd"} - set(out)
    if missing:
        raise SystemExit(f"File 7 header lacks {sorted(missing)}. Header was:\n" + "\n".join(columns))
    return out


def fetch_file_7(session: requests.Session) -> tuple[pd.DataFrame, str]:
    errors = []
    for url in FILE_7_URLS:
        try:
            r = session.get(url, timeout=120)
            r.raise_for_status()
            return pd.read_csv(io.BytesIO(r.content)), url
        except Exception as exc:  # try the next copy
            errors.append(f"{url}: {exc}")
    raise SystemExit("Could not download File 7:\n" + "\n".join(errors))


def fetch_lookup(session: requests.Session) -> tuple[pd.DataFrame | None, str]:
    """
    LSOA21CD -> MSOA21CD from the ONS Open Geography Portal, or (None, why).
    Searches the portal's ArcGIS catalogue for a hosted lookup table and
    pages through it.
    """
    try:
        r = session.get(ARCGIS_SEARCH, timeout=60, params={
            "f": "json", "num": 50,
            "q": 'LSOA21 MSOA21 lookup owner:ONSGeography_data type:"Feature Service"'})
        r.raise_for_status()
        items = r.json().get("results", [])
        items = [i for i in items if re.search(r"LSOA.*MSOA", i.get("title", ""), re.I)
                 and "2021" in i.get("title", "") and i.get("url")]
        # Exact-fit before best-fit, newest first.
        items.sort(key=lambda i: ("exact" not in i["title"].lower(), -i.get("modified", 0)))
        for item in items:
            layer = item["url"].rstrip("/") + "/0"
            meta = session.get(layer, params={"f": "json"}, timeout=60).json()
            fields = {f["name"].upper(): f["name"] for f in meta.get("fields", [])}
            if "LSOA21CD" not in fields or "MSOA21CD" not in fields:
                continue
            rows, offset = [], 0
            while True:
                page = session.get(layer + "/query", timeout=120, params={
                    "where": "1=1", "outFields": f"{fields['LSOA21CD']},{fields['MSOA21CD']}",
                    "returnGeometry": "false", "f": "json",
                    "resultOffset": offset, "resultRecordCount": 2000}).json()
                feats = page.get("features", [])
                rows += [(f["attributes"][fields["LSOA21CD"]], f["attributes"][fields["MSOA21CD"]]) for f in feats]
                if not feats or not page.get("exceededTransferLimit"):
                    break
                offset += len(feats)
            df = pd.DataFrame(rows, columns=["lsoa_code", "msoa_code"]).drop_duplicates("lsoa_code")
            if len(df) > 30_000:
                return df, f"ONS Open Geography Portal: {item['title']} ({item['url']})"
        return None, "no ONS lookup table with LSOA21CD and MSOA21CD found"
    except Exception as exc:
        return None, f"ONS lookup failed: {exc}"


def msoa_from_names(lsoa: pd.DataFrame, msoa_names: dict[str, str]) -> pd.Series:
    """The naming rule: strip the LSOA name's last letter to get its MSOA's name."""
    by_name = {n: c for c, n in msoa_names.items()}
    stem = lsoa["lsoa_name"].astype(str).str.strip().str.replace(r"[A-Z]$", "", regex=True)
    return stem.map(by_name)


def aggregate(lsoa: pd.DataFrame, msoa_names: dict[str, str]) -> pd.DataFrame:
    """Population-weighted mean of every score, per MSOA, with a fresh IMD rank."""
    scores = [k for k in DOMAINS if k in lsoa.columns]
    w = lsoa["population"].astype(float)
    parts = {"population": lsoa.groupby("msoa_code")["population"].sum(),
             "lsoas": lsoa.groupby("msoa_code").size()}
    for k in scores:
        parts[k] = (lsoa[k].astype(float) * w).groupby(lsoa["msoa_code"]).sum() / w.groupby(lsoa["msoa_code"]).sum()
    out = pd.DataFrame(parts).reset_index()
    out["msoa_name"] = out["msoa_code"].map(msoa_names)
    out["imd_rank"] = out["imd"].rank(ascending=False, method="min").astype(int)
    out["imd_decile"] = ((out["imd_rank"] - 1) * 10 // len(out) + 1).astype(int)
    cols = ["msoa_code", "msoa_name", "lsoas", "population"] + scores + ["imd_rank", "imd_decile"]
    out = out[cols].sort_values("msoa_code")
    for k in scores:
        out[k] = out[k].round(4)
    out["population"] = out["population"].round().astype(int)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, default=Path("data/db/england.db"))
    ap.add_argument("--out", type=Path, default=Path("data/msoa_deprivation.csv"))
    args = ap.parse_args()

    import sqlite3
    conn = sqlite3.connect(args.db)
    msoa_names = dict(conn.execute("SELECT msoa_code, msoa_name FROM msoa_demographics"))
    if len(msoa_names) < MIN_MSOAS:
        raise SystemExit(f"msoa_demographics holds {len(msoa_names)} MSOAs; expected about 6,856")

    session = requests.Session()
    session.headers["User-Agent"] = "english-ftbl26 deprivation fetch (GitHub Actions)"
    raw, file_url = fetch_file_7(session)
    cols = find_columns(raw.columns)
    lsoa = pd.DataFrame({k: raw[c] for k, c in cols.items()})
    print(f"File 7: {len(lsoa):,} LSOAs, columns {sorted(cols)}")

    lookup, how = fetch_lookup(session)
    if lookup is not None:
        lsoa = lsoa.merge(lookup, on="lsoa_code", how="left")
        joined = f"{how}"
    else:
        print(f"Falling back to names: {how}")
        if "lsoa_name" not in lsoa.columns:
            raise SystemExit("No ONS lookup and no LSOA names in File 7: cannot join")
        lsoa["msoa_code"] = msoa_from_names(lsoa, msoa_names)
        joined = f"LSOA name minus its final letter = MSOA name ({how})"
    unmatched = int(lsoa["msoa_code"].isna().sum())
    if unmatched > len(lsoa) * 0.001:
        raise SystemExit(f"{unmatched:,} LSOAs did not join to an MSOA; first: "
                         f"{lsoa[lsoa['msoa_code'].isna()].head(5).to_dict('records')}")
    lsoa = lsoa[lsoa["msoa_code"].isin(msoa_names)]

    out = aggregate(lsoa, msoa_names)
    if len(out) < MIN_MSOAS:
        raise SystemExit(f"Only {len(out):,} MSOAs after the join; expected about 6,856")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    meta = {
        "fetched": datetime.date.today().isoformat(),
        "source": "English Indices of Deprivation 2025, File 7 (MHCLG), Open Government Licence v3",
        "file_7_url": file_url,
        "join": joined,
        "lsoas": int(len(lsoa)), "msoas": int(len(out)), "unmatched_lsoas": unmatched,
        "method": "population-weighted mean of LSOA scores per 2021 MSOA; imd_rank over MSOAs, 1 = most deprived",
    }
    args.out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    sys.exit(main())
