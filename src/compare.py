"""
Two clubs side by side: everything the site knows about each, gathered
once per club so the comparison page can load any pair.

The page is a matchday companion. It loads a small index of every club
for the picker, then the two chosen clubs' files, and draws the rest in
the browser - 355 clubs make 62,835 pairs, which is not a number of pages
to build. So each club's file carries its own figures plus, for every
figure on the tale of the tape, where it ranks among all clubs that have
one (a percentile, 0 to 1, turned so that 1 is better when "better" has
a meaning). The page sizes each bar by that, so Walsall against Arsenal
shows how both stand in English football, not just which is bigger.

Nothing here judges the pair. The page has no verdict by design.
"""

import logging
import math
import sqlite3

import value as value_mod

logger = logging.getLogger(__name__)

# The tale of the tape: (key, section, label, better). better is "high",
# "low" (smaller wins: tier, wage share), or None (a fact, not a contest -
# being more disliked is not a win).
TAPE = [
    ("catchment_now", "Size", "People in reach now", "high"),
    ("catchment_peak", "Size", "People in reach at its peak", "high"),
    ("income", "Size", "Household income in reach", "high"),
    ("doorstep", "Size", "Share of its doorstep it keeps", "high"),
    ("capacity", "Size", "Ground capacity", "high"),
    ("top_flight", "Pedigree", "Top-flight seasons", "high"),
    ("titles", "Pedigree", "League titles since 1958/59", "high"),
    ("top_four", "Pedigree", "Top-four finishes", "high"),
    ("highest_tier", "Pedigree", "Highest tier reached", "low"),
    ("seasons", "Pedigree", "Seasons on record", "high"),
    ("win_rate", "Record", "League win rate", "high"),
    ("goals_per_game", "Record", "Goals per game", "high"),
    ("promotions", "Record", "Promotions", "high"),
    ("relegations", "Record", "Relegations", "low"),
    ("yo_yo", "Record", "Yo-yo score", None),
    ("pyramid_now", "Now", "Place in the pyramid", "low"),
    ("ppg_now", "Now", "Points per game this season", "high"),
    ("form5", "Now", "Points from the last five", "high"),
    ("momentum", "Now", "Places climbed in three seasons", "high"),
    ("turnover", "Money", "Turnover", "high"),
    ("wage_share", "Money", "Wages as a share of turnover", "low"),
    ("margin", "Money", "Profit margin", "high"),
    ("value_index", "Money", "Value index (equal weights)", "high"),
    ("ground_security", "Money", "Hold on its ground", "high"),
    ("hatred_index", "Feeling", "Hatred index (equal weights)", None),
]

STREAK_LABELS = {
    "win": "Wins in a row", "unbeaten": "Unbeaten run", "clean_sheet": "Clean sheets in a row",
    "draw": "Draws in a row", "loss": "Defeats in a row", "winless": "Without a win",
    "scoreless": "Without scoring",
}
STREAK_GOOD = {"win", "unbeaten", "clean_sheet"}

EARTH_MILES = 3958.8
MIN_SHARE = 0.05   # map points: neighbourhoods where the club draws at least this


def miles(lat1, lon1, lat2, lon2) -> float | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_MILES * math.asin(math.sqrt(a))


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _has(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone() is not None


def history(conn: sqlite3.Connection) -> dict[str, list[list]]:
    """
    {club_id: [[season, tier, pyramid_place, position, division, status], ...]}
    oldest first. pyramid_place counts every club above in every tier on
    file that season, so a tier-three champion is placed below the whole
    Championship.
    """
    place = "COALESCE(tier_position, position)" if "tier_position" in _cols(conn, "standings") else "position"
    sizes: dict[int, dict[int, int]] = {}
    for season, tier, n in conn.execute(
            "SELECT season_end_year, tier, COUNT(*) FROM standings GROUP BY season_end_year, tier"):
        sizes.setdefault(season, {})[tier] = n
    offset: dict[tuple[int, int], int] = {}
    for season, by_tier in sizes.items():
        above = 0
        for tier in sorted(by_tier):
            offset[(season, tier)] = above
            above += by_tier[tier]
    out: dict[str, list[list]] = {}
    for cid, season, tier, pos, div, status in conn.execute(
            f"SELECT club_id, season_end_year, tier, {place}, division_name, status FROM standings"
            " WHERE club_id IS NOT NULL ORDER BY season_end_year"):
        out.setdefault(cid, []).append(
            [season, tier, offset[(season, tier)] + (pos or 0), pos, div, status])
    return out


def results(conn: sqlite3.Connection) -> dict[str, list[list]]:
    """{club_id: [[date, opponent_id, opponent_name, 'H'|'A', gf, ga], ...]} newest first."""
    out: dict[str, list[list]] = {}
    if not _has(conn, "matches"):
        return out
    for date, h, a, hn, an, hg, ag in conn.execute(
            "SELECT match_date, home_club_id, away_club_id, home_name, away_name, fthg, ftag"
            " FROM matches WHERE fthg IS NOT NULL ORDER BY match_date DESC"):
        if h:
            out.setdefault(h, []).append([date, a, an, "H", hg, ag])
        if a:
            out.setdefault(a, []).append([date, h, hn, "A", ag, hg])
    return out


def form_points(matches: list[list], n: int = 5) -> int | None:
    recent = matches[:n]
    if len(recent) < n:
        return None
    return sum(3 if gf > ga else 1 if gf == ga else 0 for *_, gf, ga in recent)


def career(rows: list[list], conn: sqlite3.Connection, club_id: str) -> dict:
    r = conn.execute(
        "SELECT SUM(played), SUM(won), SUM(drawn), SUM(lost), SUM(gf), SUM(ga) FROM standings"
        " WHERE club_id = ? AND status != 'In progress'", (club_id,)).fetchone()
    p, w, d, l, gf, ga = [x or 0 for x in r]
    return {"played": p, "won": w, "drawn": d, "lost": l, "gf": gf, "ga": ga}


def same_division(a: list[list], b: list[list]) -> list[dict]:
    """Seasons both clubs spent in the same division, with where each finished."""
    bmap = {row[0]: row for row in b}
    out = []
    for row in a:
        other = bmap.get(row[0])
        if other and other[4] == row[4] and other[1] == row[1]:
            out.append({"season": row[0], "division": row[4], "a": row[3], "b": other[3],
                        "live": row[5] == "In progress"})
    return out


def standing(values: dict[str, float | None], higher_is_better: bool = True) -> dict[str, float | None]:
    """
    {id: 0..1}: the share of the other clubs with a figure that this club
    beats outright. Ties take the lower place, so the two hundred clubs
    with no title all stand at 0 rather than halfway up - a bar for
    nothing should be no bar.
    """
    known = [(v if higher_is_better else -v) for v in values.values() if v is not None]
    known.sort()
    n = len(known)
    out: dict[str, float | None] = {}
    import bisect
    for k, v in values.items():
        if v is None:
            out[k] = None
        else:
            x = v if higher_is_better else -v
            out[k] = bisect.bisect_left(known, x) / (n - 1) if n > 1 else 0.5
    return out


def assemble(conn: sqlite3.Connection, facts: dict[str, dict]) -> tuple[list[dict], dict[str, dict]]:
    """
    (index, details). index: one small row per club for the picker.
    details: {club_id: everything the page draws for that club}.
    """
    import grounds as grounds_mod
    import hatred as hatred_mod

    names = {cid: name for cid, name in conn.execute("SELECT club_id, canonical_name FROM club_master")}
    # Older databases lack the kit colours or coordinates; take what exists.
    have = _cols(conn, "club_master")
    wanted = ["color_primary", "color_secondary", "latitude", "longitude", "stadium_name"]
    sel = ", ".join(c if c in have else f"NULL AS {c}" for c in wanted)
    master = {r[0]: r for r in conn.execute(f"SELECT club_id, {sel} FROM club_master")}
    traj = {}
    if _has(conn, "club_trajectory"):
        cur = conn.execute("SELECT * FROM club_trajectory")
        cols = [d[0] for d in cur.description]
        traj = {r[0]: dict(zip(cols, r)) for r in cur}
    hist = history(conn)
    res = results(conn)
    newest = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    finished = value_mod.latest_finished_season(conn)
    live = {cid for (cid,) in conn.execute(
        "SELECT club_id FROM standings WHERE season_end_year = ? AND club_id IS NOT NULL", (newest,))}

    catch = {}
    if _has(conn, "club_catchment"):
        cur = conn.execute("SELECT * FROM club_catchment")
        cols = [d[0] for d in cur.description]
        catch = {r[0]: dict(zip(cols, r)) for r in cur}

    model = None
    try:
        import catchment as catchment_mod
        model = catchment_mod.current_shares(conn)
    except Exception as exc:  # the page must build without the map
        logger.warning("compare: catchment shares skipped: %s", exc)

    streaks: dict[str, dict] = {}
    if _has(conn, "club_streak_records"):
        for cid, kind, rec, rec_end_season, cur_len in conn.execute(
                "SELECT club_id, streak_type, record_length, record_season_end_year, current_length"
                " FROM club_streak_records"):
            streaks.setdefault(cid, {})[kind] = {"record": rec, "season": rec_end_season, "current": cur_len or 0}

    money = value_mod._finances(conn)

    hat = {}
    try:
        rows = hatred_mod.score_clubs(conn, hatred_mod.load_curated())
        norm = hatred_mod.normalised(rows)
        idx = hatred_mod.hatred_index(norm)
        hat = {r["club_id"]: {**{k: round(norm[r["club_id"]][k], 3) for k in hatred_mod.KINDS},
                              "index": round(idx[r["club_id"]], 1)} for r in rows}
    except Exception as exc:
        logger.warning("compare: hatred skipped: %s", exc)

    val = {}
    try:
        for r in value_mod.score_clubs(conn, facts):
            val[r["club_id"]] = {"index": round(value_mod.value_index(r["levers"]), 1), "levers": r["levers"]}
    except Exception as exc:
        logger.warning("compare: value skipped: %s", exc)

    titles = {}
    top_four = {}
    for cid, pos in conn.execute(
            "SELECT club_id, position FROM standings WHERE tier = 1 AND status != 'In progress'"):
        if pos == 1:
            titles[cid] = titles.get(cid, 0) + 1
        if pos and pos <= 4:
            top_four[cid] = top_four.get(cid, 0) + 1

    ids = sorted(names)
    raw: dict[str, dict[str, float | None]] = {k: {} for k, *_ in TAPE}
    details: dict[str, dict] = {}
    for cid in ids:
        f = facts.get(cid) or {}
        t = traj.get(cid) or {}
        h = hist.get(cid, [])
        m = master.get(cid)
        c = catch.get(cid) or {}
        car = career(h, conn, cid)
        played = car["played"]
        now_row = h[-1] if h and h[-1][0] == newest else None
        cur_season = conn.execute(
            "SELECT played, points, gd FROM standings WHERE club_id = ? AND season_end_year = ?",
            (cid, newest)).fetchone() if now_row else None
        hmap = {row[0]: row for row in h}
        then = hmap.get(finished - 3) if finished else None
        now_fin = hmap.get(finished) if finished else None
        fin = money.get(cid)
        ground = f.get("ground") or {}
        matches = res.get(cid, [])

        stat = {
            "catchment_now": c.get("catchment_pop_current"),
            "catchment_peak": c.get("catchment_pop_restored"),
            "income": c.get("catchment_income"),
            "doorstep": c.get("contest_ratio"),
            "capacity": f.get("capacity") if isinstance(f.get("capacity"), (int, float)) else None,
            "top_flight": t.get("seasons_in_tier1"),
            "titles": titles.get(cid, 0) if h else None,
            "top_four": top_four.get(cid, 0) if h else None,
            "highest_tier": t.get("highest_tier"),
            "seasons": len(h) or None,
            "win_rate": car["won"] / played if played else None,
            "goals_per_game": car["gf"] / played if played else None,
            "promotions": t.get("total_promotions"),
            "relegations": t.get("total_relegations"),
            "yo_yo": t.get("yo_yo_score"),
            "pyramid_now": now_row[2] if now_row else None,
            "ppg_now": (cur_season[1] / cur_season[0]) if cur_season and cur_season[0] else None,
            "form5": form_points(matches) if cid in live else None,
            "momentum": (then[2] - now_fin[2]) if then and now_fin else None,
            "turnover": fin["turnover"] if fin else None,
            "wage_share": (fin["staff"] / fin["turnover"]) if fin and fin.get("staff") else None,
            "margin": (fin["profit"] / fin["turnover"]) if fin and fin.get("profit") is not None else None,
            "value_index": val.get(cid, {}).get("index"),
            "ground_security": grounds_mod.security(ground, (newest or 2027) - 1) if ground else None,
            "hatred_index": hat.get(cid, {}).get("index"),
        }
        for k, v in stat.items():
            raw[k][cid] = v

        lat, lon = (m[3], m[4]) if m else (None, None)
        points = []
        if model is not None and cid in model.index:
            i = model.index[cid]
            share = model.share[i]
            for j in (share >= MIN_SHARE).nonzero()[0]:
                points.append([round(float(model.msoa_lat[j]), 3), round(float(model.msoa_lon[j]), 3),
                               int(model.pop[j]), round(float(share[j]), 2)])
        rival = c.get("nearest_rival_id")
        details[cid] = {
            "id": cid, "name": names[cid],
            "colors": [m[1], m[2]] if m else [None, None],
            "live": cid in live, "tier": now_row[1] if now_row else None,
            "division": now_row[4] if now_row else None,
            "first": h[0][0] if h else None, "last": h[-1][0] if h else None,
            "facts": {
                "founded": f.get("founded"), "nickname": f.get("nickname"),
                "stadium": f.get("stadium") or (m[5] if m else None), "opened": f.get("stadium_opened"),
                "capacity": stat["capacity"],
                "ground_owner": grounds_mod.describe(ground, (newest or 2027) - 1) if ground else None,
                "owner": f.get("owner"), "owner_since": f.get("owner_since"),
                "model": (f.get("ownership_model") or "").replace("_", " ") or None,
                "natural_level": t.get("natural_level_label"),
                "rival": names.get(rival) if rival else None,
                "rival_id": rival, "rival_miles": round(c["nearest_rival_miles"], 1) if c.get("nearest_rival_miles") else None,
                "administrations": len(f.get("administration") or []),
                "deductions": len(f.get("points_deductions") or []),
            },
            "career": car,
            "history": [[row[0], row[1], row[2], row[3]] for row in h],
            "divisions": {row[0]: row[4] for row in h},
            "form": matches[:10] if cid in live else [],
            "season": {"played": cur_season[0], "points": cur_season[1], "gd": cur_season[2],
                       "position": now_row[3]} if cur_season else None,
            "streaks": streaks.get(cid, {}),
            "hatred": hat.get(cid),
            "levers": val.get(cid, {}).get("levers"),
            "money": {"year": fin["year"], "turnover": fin["turnover"], "staff": fin.get("staff"),
                      "profit": fin.get("profit")} if fin else None,
            "ground": {"lat": lat, "lon": lon},
            "catchment": points,
            "stats": stat,
        }

    # Where each figure ranks among every club that has it.
    for key, _sec, _label, better in TAPE:
        pct = standing(raw[key], higher_is_better=(better != "low"))
        for cid in ids:
            details[cid].setdefault("pct", {})[key] = None if pct.get(cid) is None else round(pct[cid], 3)

    index = [{"id": cid, "name": names[cid], "tier": details[cid]["tier"], "live": details[cid]["live"],
              "last": details[cid]["last"]} for cid in ids]
    index.sort(key=lambda r: (not r["live"], r["tier"] or 99, r["name"]))
    return index, details
