"""
Which clubs should be worth more in a few years than they are now: the
levers a buyer would look at, from what this database holds.

There are no sale prices, valuations or attendances here, so this is a
construction, not a price model. Each lever is scaled 0 to 1 across every
club in this season's tiers 1-7 - a percentile, so a runaway leader (Manchester City's
catchment, say) cannot squash the rest - and the page averages them with
weights the reader moves. Equal weights by default.

    football  room to climb   tiers below its natural level
              momentum        places climbed in the pyramid over three seasons
              pedigree        the highest tier reached, then top-flight seasons
    place     catchment       people in reach if restored to its peak tier
              wealth          income of the people in reach
              own doorstep    share of the people nearest it that it keeps
    ground    capacity        the ground as built
              owns ground     club > council > third party > disputed
    risk      steadiness      a low yo-yo score
              clean record    no administration or points deduction lately
    price     cheap to buy    place in the pyramid now, lower is cheaper -
                              the only stand-in for a price, and without it
                              "value" would just mean "big"
    money     revenue         turnover against the median of its tier
              wage burden     staff costs over turnover, lower is better
              margin          profit before tax over turnover

A lever the club has no data for is None; the page counts it at the
middle (0.5) and shows it grey, so a club is never ranked on a guess
that looks like a fact. Money has its own tick box because the accounts
cover mostly the bigger clubs.

Clubs that cannot be bought - fan-owned - are flagged, as are the two
things that block promotion outright: an artificial pitch and a failed
ground grading.
"""

import sqlite3
from statistics import median

import content

GROUPS = [
    {"key": "football", "label": "Football", "color": "#2a78d6"},
    {"key": "place", "label": "Place", "color": "#eb6834"},
    {"key": "ground", "label": "Ground", "color": "#1baf7a"},
    {"key": "risk", "label": "Risk", "color": "#eda100"},
    {"key": "price", "label": "Price", "color": "#e87ba4"},
    {"key": "money", "label": "Money", "color": "#008300"},
]

LEVERS = [
    {"key": "climb", "group": "football", "label": "Room to climb",
     "note": "Tiers below its natural level. Above its level scores lowest."},
    {"key": "momentum", "group": "football", "label": "Momentum",
     "note": "Places climbed in the whole pyramid over the last three finished seasons."},
    {"key": "pedigree", "group": "football", "label": "Pedigree",
     "note": "The highest tier it has reached, then its top-flight seasons."},
    {"key": "catchment", "group": "place", "label": "Catchment",
     "note": "People in reach if it were back at its peak tier."},
    {"key": "wealth", "group": "place", "label": "Wealth",
     "note": "Average household income of the people in reach."},
    {"key": "doorstep", "group": "place", "label": "Own doorstep",
     "note": "Share of the people nearest it that it keeps from rivals."},
    {"key": "capacity", "group": "ground", "label": "Capacity",
     "note": "Seats and standing as built."},
    {"key": "owns_ground", "group": "ground", "label": "Owns ground",
     "note": "Club-owned scores 1, council 0.5, third party 0.25, disputed 0."},
    {"key": "steady", "group": "risk", "label": "Steadiness",
     "note": "A low yo-yo score: fewer promotions and relegations per season."},
    {"key": "clean", "group": "risk", "label": "Clean record",
     "note": "No administration or deduction: 1. Only older than fifteen seasons: 0.5. Recent: 0."},
    {"key": "cheap", "group": "price", "label": "Cheap to buy",
     "note": "Lower in the pyramid today. What a club costs is set mostly by its division."},
    {"key": "revenue", "group": "money", "label": "Revenue",
     "note": "Turnover against the median club in its tier, latest accounts."},
    {"key": "wages", "group": "money", "label": "Wage burden",
     "note": "Staff costs over turnover. Lower scores higher."},
    {"key": "margin", "group": "money", "label": "Margin",
     "note": "Profit before tax over turnover."},
]

MAX_TIER = 7
MOMENTUM_SEASONS = 3
CLEAN_RECENT = 15
OWNERSHIP_SCORE = {"club": 1.0, "council": 0.5, "third_party": 0.25, "disputed": 0.0}
FAN_OWNED_MODELS = {"fan_trust"}


def percentile(values: dict[str, float | None], higher_is_better: bool = True) -> dict[str, float | None]:
    """
    {id: 0..1} by rank, ties sharing their average rank; None stays None.
    One value on its own scores 0.5.
    """
    known = sorted((v if higher_is_better else -v, k) for k, v in values.items() if v is not None)
    out: dict[str, float | None] = {k: None for k in values}
    n = len(known)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and known[j + 1][0] == known[i][0]:
            j += 1
        rank = (i + j) / 2
        for m in range(i, j + 1):
            out[known[m][1]] = rank / (n - 1) if n > 1 else 0.5
        i = j + 1
    return out


def pyramid_ranks(conn: sqlite3.Connection, season: int) -> dict[str, int]:
    """{club_id: place in the whole pyramid} for one season, tiers 1-7."""
    sizes = dict(conn.execute(
        "SELECT tier, COUNT(*) FROM standings WHERE season_end_year = ? AND tier <= ? GROUP BY tier",
        (season, MAX_TIER)))
    above, offset = 0, {}
    for tier in sorted(sizes):
        offset[tier] = above
        above += sizes[tier]
    # tier_position ranks across a tier's parallel divisions; an older
    # database has only the position within the division.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(standings)")}
    place = "COALESCE(tier_position, position)" if "tier_position" in cols else "position"
    return {cid: offset[tier] + pos for cid, tier, pos in conn.execute(
        f"SELECT club_id, tier, {place} FROM standings"
        " WHERE season_end_year = ? AND tier <= ?", (season, MAX_TIER)) if pos is not None}


def latest_finished_season(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT MAX(season_end_year) FROM standings WHERE season_end_year NOT IN"
        " (SELECT season_end_year FROM standings WHERE status = 'In progress')").fetchone()
    return row[0] if row else None


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def _trouble_years(conn: sqlite3.Connection, facts: dict[str, dict]) -> dict[str, int]:
    """{club_id: season of the most recent administration or deduction}."""
    last: dict[str, int] = {}
    if _has(conn, "points_deductions"):
        for cid, year in conn.execute("SELECT club_id, MAX(season_end_year) FROM points_deductions GROUP BY club_id"):
            if year:
                last[cid] = max(last.get(cid, 0), int(year))
    for cid, f in facts.items():
        for slug in ("administration", "points-deductions"):
            for e in content.theme_events(slug, f):
                last[cid] = max(last.get(cid, 0), int(e["season_end_year"]))
    return last


def _finances(conn: sqlite3.Connection) -> dict[str, dict]:
    """The latest set of accounts per club with a turnover."""
    if not _has(conn, "club_finances"):
        return {}
    out: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT club_id, season_end_year, turnover, staff_costs, profit_before_tax"
        " FROM club_finances WHERE turnover > 0 ORDER BY season_end_year"
    ):
        out[r[0]] = {"year": r[1], "turnover": r[2], "staff": r[3], "profit": r[4]}
    return out


def score_clubs(conn: sqlite3.Connection, facts: dict[str, dict] | None = None) -> list[dict]:
    """
    One row per club in this season's tiers 1-7:
    {club_id, name, tier, levers: {key: 0..1 | None}, raw: {key: text}, flags: [...], fan_owned}.
    """
    facts = facts or {}
    if not _has(conn, "club_trajectory"):
        return []
    # Clubs in this season's tables, at this season's tier. current_tier in
    # club_trajectory is the last tier a club played in, so on its own it
    # would offer Wimbledon FC (dissolved 2004) as a Championship club.
    newest = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    clubs = conn.execute(
        "SELECT t.club_id, t.canonical_name, s.tier, t.natural_level_gap, t.highest_tier,"
        " t.seasons_in_tier1, t.yo_yo_score FROM club_trajectory t"
        " JOIN standings s ON s.club_id = t.club_id AND s.season_end_year = ?"
        " WHERE s.tier BETWEEN 1 AND ? ORDER BY t.club_id", (newest, MAX_TIER)).fetchall()
    if not clubs:
        return []
    ids = [c[0] for c in clubs]
    catch = {}
    if _has(conn, "club_catchment"):
        catch = {r[0]: r[1:] for r in conn.execute(
            "SELECT club_id, catchment_pop_restored, catchment_income, contest_ratio FROM club_catchment")}
    latest = latest_finished_season(conn)
    now_rank = pyramid_ranks(conn, latest) if latest else {}
    today_rank = pyramid_ranks(conn, newest) if newest else {}
    then_rank = pyramid_ranks(conn, latest - MOMENTUM_SEASONS) if latest else {}
    trouble = _trouble_years(conn, facts)
    money = _finances(conn)
    tier_of = {c[0]: c[2] for c in clubs}
    tier_turnover: dict[int, list[float]] = {}
    for cid, f in money.items():
        if cid in tier_of:
            tier_turnover.setdefault(tier_of[cid], []).append(f["turnover"])
    tier_median = {t: median(v) for t, v in tier_turnover.items()}

    raw: dict[str, dict[str, float | None]] = {lv["key"]: {} for lv in LEVERS}
    shown: dict[str, dict[str, str]] = {cid: {} for cid in ids}
    for cid, name, tier, gap, highest, top_seasons, yoyo in clubs:
        f = facts.get(cid) or {}
        raw["climb"][cid] = gap
        if gap is not None:
            shown[cid]["climb"] = (f"{gap} tier{'s' if abs(gap) != 1 else ''} below its level" if gap > 0
                                   else "at its level" if gap == 0 else f"{-gap} above its level")
        m = (then_rank[cid] - now_rank[cid]) if cid in now_rank and cid in then_rank else None
        raw["momentum"][cid] = m
        if m is not None:
            shown[cid]["momentum"] = f"{'up' if m >= 0 else 'down'} {abs(m)} places in {MOMENTUM_SEASONS} seasons"
        raw["pedigree"][cid] = (-highest * 1000 + (top_seasons or 0)) if highest else None
        if highest:
            shown[cid]["pedigree"] = f"peak tier {highest}, {top_seasons or 0} top-flight seasons"
        raw["cheap"][cid] = today_rank[cid]
        shown[cid]["cheap"] = f"{today_rank[cid]} in the pyramid today"
        c = catch.get(cid)
        raw["catchment"][cid] = c[0] if c else None
        raw["wealth"][cid] = c[1] if c else None
        raw["doorstep"][cid] = c[2] if c else None
        if c:
            shown[cid]["catchment"] = f"{c[0]:,} people at its peak tier" if c[0] is not None else ""
            shown[cid]["wealth"] = f"£{c[1]:,} household income" if c[1] is not None else ""
            shown[cid]["doorstep"] = f"keeps {round(100 * c[2])}% of its nearest people" if c[2] is not None else ""
        cap = f.get("capacity")
        raw["capacity"][cid] = float(cap) if isinstance(cap, (int, float)) else None
        if raw["capacity"][cid]:
            shown[cid]["capacity"] = f"{int(cap):,} capacity"
        own = f.get("stadium_ownership")
        raw["owns_ground"][cid] = OWNERSHIP_SCORE.get(own)
        if own in OWNERSHIP_SCORE:
            shown[cid]["owns_ground"] = own.replace("_", " ")
        raw["steady"][cid] = yoyo
        if yoyo is not None:
            shown[cid]["steady"] = f"yo-yo score {yoyo:.2f}"
        last = trouble.get(cid)
        if latest is None:
            raw["clean"][cid] = None
        else:
            raw["clean"][cid] = 1.0 if not last else (0.5 if last <= latest - CLEAN_RECENT else 0.0)
            shown[cid]["clean"] = "nothing on record" if not last else f"last trouble {last - 1}/{str(last)[2:]}"
        fin = money.get(cid)
        if fin:
            med = tier_median.get(tier)
            raw["revenue"][cid] = fin["turnover"] / med if med else None
            raw["wages"][cid] = fin["staff"] / fin["turnover"] if fin["staff"] is not None else None
            raw["margin"][cid] = fin["profit"] / fin["turnover"] if fin["profit"] is not None else None
            yr = f"{fin['year'] - 1}/{str(fin['year'])[2:]}"
            shown[cid]["revenue"] = f"£{fin['turnover'] / 1e6:.1f}m turnover ({yr})"
            if raw["wages"][cid] is not None:
                shown[cid]["wages"] = f"wages {round(100 * raw['wages'][cid])}% of turnover"
            if raw["margin"][cid] is not None:
                shown[cid]["margin"] = f"{round(100 * raw['margin'][cid])}% margin"
        else:
            raw["revenue"][cid] = raw["wages"][cid] = raw["margin"][cid] = None

    # Categorical levers keep their own scale; the rest become percentiles.
    scaled = {
        k: (raw[k] if k in ("owns_ground", "clean") else percentile(raw[k], higher_is_better=k not in ("steady", "wages")))
        for k in raw
    }

    rows = []
    for cid, name, tier, *_ in clubs:
        f = facts.get(cid) or {}
        flags = []
        # Only the current model: `fan_owned` in the facts is a history
        # (Brentford, Portsmouth), not a statement about today.
        fan_owned = f.get("ownership_model") in FAN_OWNED_MODELS
        if fan_owned:
            flags.append("fan-owned")
        if f.get("pitch_type") == "artificial_3g":
            flags.append("artificial pitch")
        if f.get("ground_grading_denial"):
            flags.append("failed ground grading")
        rows.append({
            "club_id": cid, "name": name, "tier": tier, "fan_owned": fan_owned, "flags": flags,
            "levers": {k: (round(scaled[k][cid], 3) if scaled[k].get(cid) is not None else None) for k in raw},
            "raw": {k: v for k, v in shown[cid].items() if v},
        })
    return rows


def value_index(levers: dict[str, float | None], weights: dict[str, float] | None = None,
                missing: float = 0.5) -> float:
    """0-100: the weighted mean of the levers, a missing one counted at `missing`."""
    weights = weights if weights is not None else {lv["key"]: 1.0 for lv in LEVERS}
    total = sum(weights.get(k, 0.0) for k in levers)
    if total <= 0:
        return 0.0
    return 100.0 * sum(weights.get(k, 0.0) * (missing if v is None else v) for k, v in levers.items()) / total


def tier_gap(rows: list[dict], weights: dict[str, float] | None = None) -> dict[str, dict]:
    """
    {club_id: {index, tier_mean, gap}}: the index against the average
    index of every club in the same tier, at the same weights. A positive
    gap is a club the table rates higher than its division does - the
    shortlist a buyer wants, since the division is most of the price.
    """
    index = {r["club_id"]: value_index(r["levers"], weights) for r in rows}
    by_tier: dict[int, list[float]] = {}
    for r in rows:
        by_tier.setdefault(r["tier"], []).append(index[r["club_id"]])
    mean = {t: sum(v) / len(v) for t, v in by_tier.items()}
    return {r["club_id"]: {"index": index[r["club_id"]], "tier_mean": mean[r["tier"]],
                           "gap": index[r["club_id"]] - mean[r["tier"]]} for r in rows}
