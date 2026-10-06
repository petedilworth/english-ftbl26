"""
Income around the ground: where the money is, which clubs draw from it,
and whether it buys them anything.

The source is one figure per ONS neighbourhood (MSOA): net household
income after housing costs, with a 95% confidence interval. There is no
spread of income inside a neighbourhood in the data, so the spread here
is across neighbourhoods: for each club, the population-weighted
standard deviation of income over the areas it draws from, and the gap
between its richest tenth and poorest tenth of people. Both are
weighted by the catchment model's shares (src/catchment.py), so a
neighbourhood a club barely reaches barely counts.

The question the page argues is whether money near the ground buys
tiers. It does not: across this season's clubs the correlation between
catchment income and tier is close to zero, while catchment size alone
explains ninety per cent of the variance. The richest catchments belong
to suburban London clubs in the sixth and seventh tiers; the top flight
lives in the industrial north-west, among the poorest.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)

MIN_PEOPLE = 1_000      # a catchment smaller than this is noise
MAX_TIER = 7
# The blue sequential ramp (dataviz reference palette, steps 100-700).
RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
        "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]


def _weighted(values, weights):
    """Population-weighted mean, standard deviation and 10th/90th percentiles."""
    import numpy as np

    total = float(weights.sum())
    if total <= 0:
        return None
    mean = float((weights * values).sum() / total)
    sd = float(np.sqrt((weights * (values - mean) ** 2).sum() / total))
    order = np.argsort(values)
    cum = np.cumsum(weights[order]) / total
    # side="right": the value the first person past the cut-off earns, so a
    # tenth of the people at exactly the boundary fall on the lower side.
    p10 = float(values[order][min(len(values) - 1, int(np.searchsorted(cum, 0.10, side="right")))])
    p90 = float(values[order][min(len(values) - 1, int(np.searchsorted(cum, 0.90, side="right")))])
    return {"mean": mean, "sd": sd, "p10": p10, "p90": p90}


def tier_model(tiers, people):
    """
    tier = a + b * log(people): what a club's size alone predicts, and how
    much of the variance it explains. Returns (a, b, r2, predicted).
    """
    import numpy as np

    T = np.asarray(tiers, float)
    P = np.log(np.asarray(people, float))
    if len(T) < 3 or T.std() == 0:
        return 0.0, 0.0, 0.0, T
    X = np.column_stack([np.ones(len(T)), P])
    beta, *_ = np.linalg.lstsq(X, T, rcond=None)
    pred = X @ beta
    r2 = 1 - float(((T - pred) ** 2).sum() / ((T - T.mean()) ** 2).sum())
    return float(beta[0]), float(beta[1]), r2, pred


def assemble(conn: sqlite3.Connection) -> dict:
    """Everything the page draws; {} when the demographics are absent."""
    import numpy as np

    import catchment

    g = catchment._gravity(conn)
    if g is None:
        return {}
    msoas, clubs_df, dist, pull, _pr, denom = g
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.where(denom > 0, pull / denom, 0.0)
    pop = msoas["population"].to_numpy(float)
    inc = msoas["net_income"].to_numpy(float)
    # The gravity frame carries only what the model needs; names and the
    # confidence intervals come from the same table, aligned by code.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(msoa_demographics)")}
    extra = {}
    if {"msoa_name", "income_ci_lower", "income_ci_upper"} <= cols:
        extra = {r[0]: r[1:] for r in conn.execute(
            "SELECT msoa_code, msoa_name, income_ci_lower, income_ci_upper FROM msoa_demographics")}
    codes = msoas["msoa_code"].tolist()
    names_msoa = [(extra.get(c) or ("", None, None))[0] or c for c in codes]
    lo = np.array([(extra.get(c) or (None, None, None))[1] or inc[j] for j, c in enumerate(codes)], float)
    hi = np.array([(extra.get(c) or (None, None, None))[2] or inc[j] for j, c in enumerate(codes)], float)
    las = msoas["local_authority"].fillna("").tolist()

    england = _weighted(inc, pop)
    newest = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    tier_now = dict(conn.execute(
        "SELECT club_id, tier FROM standings WHERE season_end_year = ? AND tier <= ? AND club_id IS NOT NULL",
        (newest, MAX_TIER)))
    names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))

    clubs = []
    model_index: dict[str, int] = {}
    for i, cid in enumerate(clubs_df["club_id"].tolist()):
        if cid not in tier_now:
            continue
        w = share[i] * pop
        stats = _weighted(inc, w)
        if not stats or w.sum() < MIN_PEOPLE:
            continue
        drawn = np.where(w > 0)[0]
        richest = int(drawn[np.argmax(inc[drawn])])
        poorest = int(drawn[np.argmin(inc[drawn])])
        # The richest and poorest places it draws a real share from (at
        # least one person in ten), not a stray fraction of a far suburb.
        meaningful = drawn[share[i][drawn] >= 0.10]
        if len(meaningful):
            richest = int(meaningful[np.argmax(inc[meaningful])])
            poorest = int(meaningful[np.argmin(inc[meaningful])])
        model_index[cid] = len(clubs)
        clubs.append({
            "club_id": cid, "name": names.get(cid, cid), "tier": tier_now[cid],
            "lat": float(clubs_df["latitude"].iloc[i]), "lon": float(clubs_df["longitude"].iloc[i]),
            "people": int(round(w.sum())),
            "mean": int(round(stats["mean"])), "sd": int(round(stats["sd"])),
            "p10": int(round(stats["p10"])), "p90": int(round(stats["p90"])),
            "gap": int(round(stats["p90"] - stats["p10"])),
            "vs_england": int(round(stats["mean"] - england["mean"])),
            "richest": {"name": names_msoa[richest], "la": las[richest], "income": int(inc[richest]),
                        "share": round(float(share[i][richest]), 2)},
            "poorest": {"name": names_msoa[poorest], "la": las[poorest], "income": int(inc[poorest]),
                        "share": round(float(share[i][poorest]), 2)},
            "_row": i,
        })
    if not clubs:
        return {}

    a, b, r2, pred = tier_model([c["tier"] for c in clubs], [c["people"] for c in clubs])
    incomes = np.array([c["mean"] for c in clubs], float)
    tiers = np.array([c["tier"] for c in clubs], float)
    spread_ok = tiers.std() > 0 and incomes.std() > 0 and len(clubs) >= 3
    corr_income = float(np.corrcoef(tiers, incomes)[0, 1]) if spread_ok else 0.0
    corr_people = float(np.corrcoef(tiers, np.log([c["people"] for c in clubs]))[0, 1]) if spread_ok else 0.0
    # Income's extra explanatory power once size is in: tiers per £1,000.
    X = np.column_stack([np.ones(len(tiers)), np.log([c["people"] for c in clubs]), (incomes - england["mean"]) / 1000])
    beta2, *_ = np.linalg.lstsq(X, tiers, rcond=None)
    pred2 = X @ beta2
    r2_both = (1 - float(((tiers - pred2) ** 2).sum() / ((tiers - tiers.mean()) ** 2).sum())) if spread_ok else 0.0
    for c, p in zip(clubs, pred):
        c["predicted"] = round(float(p), 1)
        c["residual"] = round(c["tier"] - float(p), 1)   # positive: lower than its size predicts

    q75, q25 = float(np.percentile(incomes, 75)), float(np.percentile(incomes, 25))
    by_tier = {}
    for t in range(1, MAX_TIER + 1):
        v = [c["mean"] for c in clubs if c["tier"] == t]
        if v:
            by_tier[t] = {"n": len(v), "median": int(np.median(v)), "min": min(v), "max": max(v)}

    # The map: every neighbourhood, with the club that draws most of it.
    winner = share.argmax(axis=0)
    points = []
    for j in range(len(pop)):
        w_idx = int(winner[j])
        w_cid = clubs_df["club_id"].iloc[w_idx]
        points.append([round(float(msoas["latitude"].iloc[j]), 4), round(float(msoas["longitude"].iloc[j]), 4),
                       int(inc[j]), int(pop[j]), model_index.get(w_cid, -1), int(lo[j]), int(hi[j])])
    edges = [int(np.percentile(inc, q)) for q in np.linspace(0, 100, len(RAMP) + 1)[1:-1]]

    def strip(c):
        return {k: c[k] for k in ("club_id", "name", "tier", "people", "mean", "sd", "p10", "p90", "gap",
                                  "vs_england", "richest", "poorest", "predicted", "residual")}

    ranked = sorted(clubs, key=lambda c: -c["mean"])
    la_index: dict[str, int] = {}
    return {
        "england": {k: int(round(v)) for k, v in england.items()},
        "clubs": [strip(c) for c in clubs],
        "by_tier": by_tier,
        "model": {"corr_income": round(corr_income, 2), "corr_people": round(corr_people, 2),
                  "r2_people": round(r2, 2), "r2_both": round(r2_both, 2),
                  "per_thousand": round(float(beta2[2]), 3), "n": len(clubs)},
        "richest": [strip(c) for c in ranked[:12]],
        "poorest": [strip(c) for c in ranked[-12:][::-1]],
        "most_unequal": [strip(c) for c in sorted(clubs, key=lambda c: -c["sd"])[:12]],
        "least_unequal": [strip(c) for c in sorted(clubs, key=lambda c: c["sd"])[:8]],
        "rich_town_small_club": [strip(c) for c in sorted(
            (c for c in clubs if c["mean"] >= q75 and c["tier"] >= 4), key=lambda c: -c["mean"])[:12]],
        "poor_town_big_club": [strip(c) for c in sorted(
            (c for c in clubs if c["mean"] <= q25 and c["tier"] <= 2), key=lambda c: c["mean"])[:12]],
        "quartiles": {"q25": int(q25), "q75": int(q75)},
        "map": {"points": points, "edges": edges, "ramp": RAMP,
                "clubs": [{"id": c["club_id"], "name": c["name"], "tier": c["tier"], "lat": c["lat"], "lon": c["lon"],
                           "mean": c["mean"], "sd": c["sd"], "gap": c["gap"], "people": c["people"]} for c in clubs],
                # "Wirral 016" is stored as "016" against its authority: the
                # names alone would be a third of the file.
                "names": [n[len(la) + 1:] if la and n.startswith(la + " ") else n for n, la in zip(names_msoa, las)],
                "las": [la_index.setdefault(la, len(la_index)) for la in las],
                "authorities": list(la_index)},
        "season": newest,
    }
