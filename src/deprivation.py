"""
Deprivation around the ground: the English Indices of Deprivation 2025,
neighbourhood by neighbourhood, through the catchment model.

The source is data/msoa_deprivation.csv, written by
scripts/fetch_deprivation.py from MHCLG's File 7: seven domain scores and
two supplementary ones for each of England's 6,856 MSOAs, rolled up from
small areas by population.

The domain scores sit on different scales (income and employment are
rates; the rest are standardised scores), so nothing here adds them raw.
Each is turned into a population-weighted percentile across England -
50 is the average person's neighbourhood, 100 the most deprived - and the
page's sliders weight those. At the official domain weights this tracks
the published index closely but is not it: MHCLG combines exponentially
transformed ranks, which leans harder on the very worst places.

A club's figure for a domain is the average percentile of the people it
draws, weighted by the catchment model's shares, exactly as the income
page weights income. Because that is linear, any weighting of domains for
a club is the same weighting of its per-domain figures, so the browser
can re-rank every club without the catchment matrix.

The finding the page has to state plainly: clubs in the top tiers draw
from more deprived places, but only because big clubs sit in big old
towns. Hold catchment size fixed and the link with tier disappears.
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
SOURCE = PROJECT_ROOT / "data" / "msoa_deprivation.csv"
MAX_TIER = 7
MIN_PEOPLE = 1_000

# key, label, official weight in the Index of Multiple Deprivation, what it measures.
DOMAINS = [
    ("income", "Income", 22.5, "Share of people on low-income benefits"),
    ("employment", "Employment", 22.5, "Share of working-age people out of work through sickness, disability or unemployment"),
    ("education", "Education", 13.5, "Children's attainment and adults without qualifications or English"),
    ("health", "Health", 13.5, "Early deaths, disability, emergency admissions, anxiety and depression"),
    ("crime", "Crime", 9.3, "Recorded violence, burglary, theft and criminal damage"),
    ("housing", "Housing & services", 9.3, "Distance to a GP, school or shop; overcrowding, homelessness, unaffordability"),
    ("environment", "Living environment", 9.3, "Housing in poor condition or without central heating; air quality; road accidents"),
    ("idaci", "Child poverty", 0.0, "Share of children in income-deprived families"),
    ("idaopi", "Pensioner poverty", 0.0, "Share of people over 60 who are income deprived"),
]
KEYS = [d[0] for d in DOMAINS]
OFFICIAL = [d[2] for d in DOMAINS]
# Clubs whose shapes differ most, for the shape panel's quick picks.
FEATURED = ["hartlepool-united-fc", "west-ham-united-fc", "ramsgate-fc", "fc-halifax-town", "st-albans-city-fc"]


def percentiles(values, weights):
    """Population-weighted percentile of each value, 0-100, higher = more deprived."""
    import numpy as np

    v = np.asarray(values, float)
    w = np.asarray(weights, float)
    order = np.argsort(v, kind="mergesort")
    cum = np.cumsum(w[order])
    total = cum[-1] if len(cum) else 1.0
    mid = (cum - w[order] / 2) / total * 100     # the middle of each neighbourhood's slice of people
    out = np.empty_like(v)
    out[order] = mid
    return out


def index(pcts, weights):
    """Weighted mean of domain percentiles (rows x domains) at these weights."""
    import numpy as np

    w = np.asarray(weights, float)
    if w.sum() <= 0:
        return np.full(len(pcts), 50.0)
    return np.asarray(pcts, float) @ w / w.sum()


def load(path: Path = SOURCE):
    import pandas as pd

    if not Path(path).exists():
        return None
    df = pd.read_csv(path)
    missing = (set(KEYS) | {"imd"}) - set(df.columns)
    if missing:
        logger.warning("deprivation file lacks %s", sorted(missing))
        return None
    return df.set_index("msoa_code")


def _partial_corr(y, x, control):
    """Correlation of y and x once a linear control is taken out of both."""
    import numpy as np

    X = np.column_stack([np.ones(len(control)), control])
    ry = y - X @ np.linalg.lstsq(X, y, rcond=None)[0]
    rx = x - X @ np.linalg.lstsq(X, x, rcond=None)[0]
    if ry.std() == 0 or rx.std() == 0:
        return 0.0
    return float(np.corrcoef(ry, rx)[0, 1])


def assemble(conn: sqlite3.Connection, path: Path = SOURCE) -> dict:
    """Everything the page draws; {} without the file or the catchment model."""
    import numpy as np

    import catchment

    dep = load(path)
    if dep is None:
        return {}
    g = catchment._gravity(conn)
    if g is None:
        return {}
    msoas, clubs_df, _dist, pull, _pr, denom = g
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.where(denom > 0, pull / denom, 0.0)
    codes = msoas["msoa_code"].tolist()
    D = dep.reindex(codes)
    have = D["imd"].notna().to_numpy()
    if have.sum() < 0.9 * len(codes):
        logger.warning("deprivation covers %d of %d neighbourhoods", have.sum(), len(codes))
        return {}
    pop = msoas["population"].to_numpy(float)
    inc = msoas["net_income"].to_numpy(float)
    # Percentiles over England's people, then neighbourhoods without a score sit at 50.
    P = np.full((len(codes), len(KEYS)), 50.0)
    for k, key in enumerate(KEYS):
        P[have, k] = percentiles(D[key].to_numpy(float)[have], pop[have])
    raw_imd = D["imd"].to_numpy(float)
    decile = D["imd_decile"].to_numpy(float) if "imd_decile" in D.columns else np.full(len(codes), np.nan)

    newest = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    tier_now = dict(conn.execute(
        "SELECT club_id, tier FROM standings WHERE season_end_year = ? AND tier <= ? AND club_id IS NOT NULL",
        (newest, MAX_TIER)))
    names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))

    clubs = []
    for i, cid in enumerate(clubs_df["club_id"].tolist()):
        if cid not in tier_now:
            continue
        w = share[i] * pop * have
        total = w.sum()
        if total < MIN_PEOPLE:
            continue
        dom = (w @ P) / total
        clubs.append({
            "club_id": cid, "name": names.get(cid, cid), "tier": tier_now[cid],
            "lat": round(float(clubs_df["latitude"].iloc[i]), 4), "lon": round(float(clubs_df["longitude"].iloc[i]), 4),
            "people": int(round(total)),
            "d": [round(float(x), 1) for x in dom],
            "official": round(float(index(dom[None, :], OFFICIAL)[0]), 1),
            "imd": round(float(np.nansum(w * raw_imd) / total), 1),
            "income": int(round(float((w * inc).sum() / total))),
            "bottom10": round(float(w[decile == 1].sum() / total), 3),
        })
    if len(clubs) < 2:
        return {}

    tiers = np.array([c["tier"] for c in clubs], float)
    size = np.log([c["people"] for c in clubs])
    imd = np.array([c["imd"] for c in clubs], float)
    incomes = np.array([c["income"] for c in clubs], float)
    ok = tiers.std() > 0 and imd.std() > 0
    model = {
        "n": len(clubs),
        "corr_tier": round(float(np.corrcoef(tiers, imd)[0, 1]), 2) if ok else 0.0,
        "corr_size": round(float(np.corrcoef(size, imd)[0, 1]), 2) if ok else 0.0,
        "partial": round(_partial_corr(tiers, imd, size), 2) if ok else 0.0,
        "corr_income": round(float(np.corrcoef(incomes, imd)[0, 1]), 2) if ok and incomes.std() > 0 else 0.0,
        "b10_top": round(float(np.median([c["bottom10"] for c in clubs if c["tier"] <= 2] or [0])), 3),
        "b10_bottom": round(float(np.median([c["bottom10"] for c in clubs if c["tier"] >= 6] or [0])), 3),
    }
    by_tier = {}
    for t in range(1, MAX_TIER + 1):
        v = [c["official"] for c in clubs if c["tier"] == t]
        if v:
            by_tier[t] = {"n": len(v), "median": round(float(np.median(v)), 1)}

    # Where the two measures of hard times disagree: z-scores of deprivation
    # and of income after housing costs, added. High: deprived despite money.
    z_i = (imd - imd.mean()) / (imd.std() or 1)
    z_m = (incomes - incomes.mean()) / (incomes.std() or 1)
    for c, a, b in zip(clubs, z_i, z_m):
        c["disagree"] = round(float(a + b), 2)

    def strip(c):
        return {k: c[k] for k in ("club_id", "name", "tier", "people", "d", "official", "imd", "income", "bottom10", "disagree")}

    def top(key, n=10, reverse=True, where=lambda c: True):
        return [strip(c) for c in sorted((c for c in clubs if where(c)), key=lambda c: c[key], reverse=reverse)[:n]]

    k_idaci, k_idaopi = KEYS.index("idaci"), KEYS.index("idaopi")
    las = msoas["local_authority"].fillna("").tolist()
    names_msoa = D["msoa_name"].fillna("").tolist() if "msoa_name" in D.columns else [""] * len(codes)
    la_index: dict[str, int] = {}
    # [lat, lon, then one 0-100 percentile per domain]: 6,856 of them, so kept lean.
    points = [[round(float(msoas["latitude"].iloc[j]), 3), round(float(msoas["longitude"].iloc[j]), 3)]
              + [int(round(x)) for x in P[j]] for j in range(len(codes))]
    return {
        "domains": [{"key": k, "label": lbl, "weight": wt, "desc": desc} for k, lbl, wt, desc in DOMAINS],
        "clubs": [strip(c) for c in clubs],
        "model": model,
        "by_tier": by_tier,
        "most": top("official"),
        "least": top("official", reverse=False),
        "deprived_not_poor": top("disagree"),
        "poor_not_deprived": top("disagree", reverse=False),
        "bottom10": top("bottom10", 12),
        "children": sorted((strip(c) for c in clubs), key=lambda c: -c["d"][k_idaci])[:8],
        "pensioners": sorted((strip(c) for c in clubs), key=lambda c: -c["d"][k_idaopi])[:8],
        "featured": [f for f in FEATURED if any(c["club_id"] == f for c in clubs)],
        "map": {
            "points": points,
            "names": [n[len(la) + 1:] if la and n.startswith(la + " ") else n for n, la in zip(names_msoa, las)],
            "las": [la_index.setdefault(la, len(la_index)) for la in las],
            "authorities": list(la_index),
            "clubs": [{"id": c["club_id"], "name": c["name"], "tier": c["tier"], "lat": c["lat"], "lon": c["lon"],
                       "people": c["people"], "d": c["d"], "b10": c["bottom10"]} for c in clubs],
        },
        "england_imd": round(float(np.nansum(raw_imd * pop) / pop[have].sum()), 1),
        "season": newest,
    }
