"""
Why some clubs are disliked more than others: four kinds, scored apart.

    envied    what a club has won - titles and top-four finishes since
              1958/59, the last ten seasons counting double.
    resented  what it spends and who pays - wage bill rank within its
              division, ownership other supporters hold against it, and
              sanctions under the financial rules.
    mocked    fame without reward - top-flight seasons since the last
              title, and the near misses in that time. Tottenham's column.
    despised  on principle - things a club did, from content/hatred.yml,
              each with a source note and a weight.

Plus exposure, which is not a kind of dislike but a precondition for it:
how many clubs sit within fifteen miles, and how many people are in
reach. It is shown beside the four and never multiplied in; multiplying
would turn the page into a fame index, which is what every poll on this
subject already is.

The weights below are judgement. They are here, named, so the page can
show its working and a reader can disagree with a number rather than a
feeling.
"""

import logging
import math
import sqlite3
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CURATED = PROJECT_ROOT / "content" / "hatred.yml"

KINDS = ("envied", "resented", "mocked", "despised")

# Envied: a title is worth three top-four finishes; the recent ten seasons
# count double, because envy fades.
TITLE = 3.0
TOP_FOUR = 1.0
RECENT_SEASONS = 10
RECENT_MULTIPLIER = 2.0

# Resented: wage bill in the top of the division, ownership from the
# curated file, financial-rules sanctions.
WAGE_SCALE = 4.0
SANCTION = 2.0

# Mocked: ten top-flight seasons without a title is one point; every
# top-four finish without a title is one point.
DROUGHT_PER_SEASON = 0.1
NEAR_MISS = 1.0

# Exposure.
NEIGHBOUR_MILES = 15.0
EARTH_MILES = 3958.8


def load_curated(path: Path | None = None) -> dict:
    # Resolved at call time, not bound as a default: a test that points
    # CURATED elsewhere must be read from there.
    path = path or CURATED
    if not path.exists():
        return {"despised": [], "resented": [], "wear_it": [], "eras": [], "surveys": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for key in ("despised", "resented", "wear_it", "eras", "surveys"):
        data.setdefault(key, [])
    return data


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,)).fetchone() is not None


def _miles(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_MILES * math.asin(math.sqrt(h))


# ── The record ─────────────────────────────────────────────────────────────

def top_flight_record(conn: sqlite3.Connection) -> dict[str, list[tuple[int, int]]]:
    """club_id -> [(season_end_year, position)] in tier 1, completed seasons only."""
    out: dict[str, list[tuple[int, int]]] = {}
    for club_id, year, pos in conn.execute(
            "SELECT club_id, season_end_year, position FROM standings"
            " WHERE tier = 1 AND club_id IS NOT NULL AND status != 'In progress'"
            " ORDER BY season_end_year"):
        out.setdefault(club_id, []).append((year, pos))
    return out


def envied_score(seasons: list[tuple[int, int]], latest: int) -> float:
    score = 0.0
    for year, pos in seasons:
        points = TITLE if pos == 1 else TOP_FOUR if pos <= 4 else 0.0
        if points and year > latest - RECENT_SEASONS:
            points *= RECENT_MULTIPLIER
        score += points
    return score


def success_score(seasons: list[tuple[int, int]]) -> float:
    """The scatter's x axis: the same record, unweighted by recency."""
    return sum(TITLE if pos == 1 else TOP_FOUR if pos <= 4 else 0.0 for _, pos in seasons)


def mocked_score(seasons: list[tuple[int, int]]) -> tuple[float, dict]:
    """
    Fame without reward. Everything since the last title: top-flight
    seasons at a tenth of a point each, top-four finishes at a point.
    """
    titles = [year for year, pos in seasons if pos == 1]
    last_title = max(titles) if titles else None
    since = [(y, p) for y, p in seasons if last_title is None or y > last_title]
    drought = len(since)
    near = sum(1 for _, p in since if p <= 4)
    detail = {"last_title": last_title, "top_flight_seasons_since": drought, "near_misses": near}
    return DROUGHT_PER_SEASON * drought + NEAR_MISS * near, detail


def wage_percentiles(conn: sqlite3.Connection) -> dict[str, float]:
    """
    0..1, where 1 is the biggest wage bill in its division in the latest
    season with accounts. Only clubs with staff costs on file.
    """
    if not _has(conn, "club_finances"):
        return {}
    rows = conn.execute(
        """
        SELECT f.club_id, f.staff_costs, s.tier, s.division_id
        FROM club_finances f
        JOIN standings s ON s.club_id = f.club_id AND s.season_end_year = f.season_end_year
        WHERE f.staff_costs IS NOT NULL
          AND f.season_end_year = (SELECT MAX(season_end_year) FROM club_finances f2
                                   WHERE f2.club_id = f.club_id AND f2.staff_costs IS NOT NULL)
        """).fetchall()
    by_div: dict = {}
    for club_id, wages, tier, div in rows:
        by_div.setdefault(div or tier, []).append((club_id, float(wages)))
    out = {}
    for members in by_div.values():
        members.sort(key=lambda m: m[1])
        n = len(members)
        for rank, (club_id, _) in enumerate(members, start=1):
            out[club_id] = rank / n if n > 1 else 1.0
    return out


def financial_sanctions(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Financial-rules deductions in the top flight only. A Championship
    club docked for breaching its business plan is pitied, not resented;
    the first run of this model put Reading second behind Manchester
    City on the strength of three of them.
    """
    if not _has(conn, "points_deductions"):
        return {}
    return dict(conn.execute(
        "SELECT club_id, COUNT(*) FROM points_deductions"
        " WHERE category = 'financial-rules' AND club_id IS NOT NULL AND tier = 1 GROUP BY club_id"))


def exposure(conn: sqlite3.Connection) -> dict[str, dict]:
    """Neighbours within fifteen miles (tiers 1-5), and people in reach."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(club_master)")}
    if not {"latitude", "longitude"} <= cols:
        return {}          # a database with no grounds placed: no exposure to measure
    grounds = conn.execute(
        "SELECT club_id, latitude, longitude, current_tier FROM club_master"
        " WHERE latitude IS NOT NULL AND longitude IS NOT NULL").fetchall()
    pop = dict(conn.execute("SELECT club_id, catchment_pop_current FROM club_catchment")) \
        if _has(conn, "club_catchment") else {}
    out = {}
    for cid, lat, lon, tier in grounds:
        near = sum(1 for oid, olat, olon, otier in grounds
                   if oid != cid and otier and 1 <= otier <= 5
                   and _miles(lat, lon, olat, olon) <= NEIGHBOUR_MILES)
        out[cid] = {"neighbours": near, "people": int(pop.get(cid) or 0)}
    return out


# ── Scores ─────────────────────────────────────────────────────────────────

def score_clubs(conn: sqlite3.Connection, curated: dict | None = None) -> list[dict]:
    """One row per club with a top-flight season on file, all four kinds."""
    curated = curated or load_curated()
    names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))
    tiers = dict(conn.execute("SELECT club_id, current_tier FROM club_master"))
    record = top_flight_record(conn)
    latest = conn.execute("SELECT MAX(season_end_year) FROM standings WHERE status != 'In progress'").fetchone()[0] or 0
    wages = wage_percentiles(conn)
    sanctions = financial_sanctions(conn)
    expo = exposure(conn)

    curated_by: dict[str, dict[str, list]] = {}
    for kind in ("despised", "resented"):
        for e in curated.get(kind) or []:
            if isinstance(e, dict) and e.get("club"):
                curated_by.setdefault(e["club"], {}).setdefault(kind, []).append(e)

    # Every club with a top-flight season, plus any the curated file names:
    # MK Dons have never played in the top flight and are the point of the
    # despised column.
    scored = set(record) | set(curated_by) | {e.get("club") for e in curated.get("wear_it") or []
                                               if isinstance(e, dict) and e.get("club")}
    rows = []
    for club_id in scored:
        if club_id not in names:
            logger.warning("hatred.yml names %r, which is not a club_id - skipping", club_id)
            continue
        seasons = record.get(club_id, [])
        mocked, mocked_detail = mocked_score(seasons)
        cur = curated_by.get(club_id, {})
        resented = (WAGE_SCALE * wages.get(club_id, 0.0)
                    + SANCTION * sanctions.get(club_id, 0)
                    + sum(float(e.get("weight") or 0) for e in cur.get("resented", [])))
        despised = sum(float(e.get("weight") or 0) for e in cur.get("despised", []))
        rows.append({
            "club_id": club_id, "name": names.get(club_id, club_id), "tier": tiers.get(club_id),
            "success": success_score(seasons),
            "envied": envied_score(seasons, latest),
            "resented": resented, "mocked": mocked, "despised": despised,
            "titles": sum(1 for _, p in seasons if p == 1),
            "top_four": sum(1 for _, p in seasons if p <= 4),
            "top_flight_seasons": len(seasons),
            "mocked_detail": mocked_detail,
            "wage_percentile": wages.get(club_id),
            "sanctions": sanctions.get(club_id, 0),
            "events": {k: [{"year": e.get("year"), "weight": e.get("weight"), "what": " ".join(str(e.get("what", "")).split())}
                           for e in v] for k, v in cur.items()},
            "exposure": expo.get(club_id, {"neighbours": 0, "people": 0}),
        })
    rows.sort(key=lambda r: r["name"])
    return rows


def decade_picks(conn: sqlite3.Connection, curated: dict | None = None) -> list[dict]:
    """
    The model's villain of each decade - the club with most envy in it -
    beside the editorial one, and whether they agree.
    """
    curated = curated or load_curated()
    names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))
    record = top_flight_record(conn)
    editorial = {int(e["decade"]): e for e in curated.get("eras") or [] if isinstance(e, dict) and e.get("decade")}
    by_decade: dict[int, dict[str, float]] = {}
    for club_id, seasons in record.items():
        for year, pos in seasons:
            # 1959/60 is the 1960s: the season ends in the decade it belongs to.
            decade = (year // 10) * 10
            points = TITLE if pos == 1 else TOP_FOUR if pos <= 4 else 0.0
            if points:
                by_decade.setdefault(decade, {})[club_id] = by_decade.setdefault(decade, {}).get(club_id, 0.0) + points
    out = []
    # The record starts at 1958/59: one season is not a decade.
    for decade in sorted(d for d in set(by_decade) | set(editorial) if d >= 1960):
        scores = by_decade.get(decade, {})
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        model = ranked[0][0] if ranked else None
        ed = editorial.get(decade, {})
        out.append({
            "decade": decade, "label": f"{decade}s",
            "model": model, "model_name": names.get(model, model or ""),
            "model_points": ranked[0][1] if ranked else 0.0,
            "runner_up": names.get(ranked[1][0], ranked[1][0]) if len(ranked) > 1 else "",
            "editorial": ed.get("club"), "editorial_name": names.get(ed.get("club"), ed.get("club") or ""),
            "why": " ".join(str(ed.get("why", "")).split()),
            "agree": bool(model and ed.get("club") == model),
        })
    return out


def intruder_map(model, names: dict[str, str], top_n: int = 8, min_share: float = 0.15) -> dict:
    """
    For the map: each neighbourhood where some club that is not its local
    club draws at least min_share of it, coloured by that club. Only the
    top_n intruders nationally get a colour; the rest are one grey.
    """
    import numpy as np

    share = model.share.copy()
    share[model.nearest, np.arange(share.shape[1])] = 0.0        # remove the local club
    intruder = share.argmax(axis=0)
    intruder_share = share[intruder, np.arange(share.shape[1])]
    taken = np.zeros(len(model.club_ids))
    np.add.at(taken, intruder, intruder_share * model.pop)
    order = np.argsort(-taken)[:top_n]
    coloured = {int(i): n for n, i in enumerate(order)}
    points = []
    for j in np.flatnonzero(intruder_share >= min_share):
        i = int(intruder[j])
        points.append([round(float(model.msoa_lat[j]), 4), round(float(model.msoa_lon[j]), 4),
                       int(model.pop[j]), coloured.get(i, -1), round(float(intruder_share[j]), 2)])
    legend = [{"club_id": model.club_ids[int(i)], "name": names.get(model.club_ids[int(i)], model.club_ids[int(i)]),
               "people": int(taken[int(i)])} for i in order]
    return {"points": points, "legend": legend, "min_share": min_share}
