"""
Fallen giants and risers: the clubs furthest from where they were, the
odds of coming back, the fastest falls and climbs, and the clubs whose
towns say they should be higher - or lower - than they are.

Everything rests on the standings since 1958/59 (one tier per club per
season, the highest where a club appears twice). "Now" is the season in
progress. A club is a fallen giant if it has played in the top flight
since 1958/59 and is now in the third tier or below; a riser if it is in
the top two now and has been in the fourth tier or below since 1958/59.

The return odds are survival odds. A relegation from the top flight
starts a clock; the clock stops when the club is back. A relegation too
recent to have run k seasons is left out of the k-season figure rather
than counted as "not back", which would make the odds look worse than
they are.

The size model is src/income.py's: a club's expected tier from the number
of people its catchment draws. Welsh clubs are left out of it, because
the catchment counts English neighbourhoods only and so undercounts them.
"""

import collections
import sqlite3

WELSH = {"cardiff-city-fc", "swansea-city-fc", "newport-county-fc", "wrexham-fc", "merthyr-tydfil-fc",
         "colwyn-bay-fc", "bangor-city-fc"}
MAX_TIER = 7


def histories(conn: sqlite3.Connection) -> dict[str, dict[int, int]]:
    """club_id -> {season: tier}, tiers 1-7, the highest tier where a club appears twice."""
    out: dict[str, dict[int, int]] = collections.defaultdict(dict)
    for cid, season, tier in conn.execute(
            "SELECT club_id, season_end_year, tier FROM standings WHERE club_id IS NOT NULL AND tier <= ?",
            (MAX_TIER,)):
        out[cid][season] = min(tier, out[cid].get(season, 99))
    return dict(out)


def champions_fell(conn: sqlite3.Connection, hist: dict, latest: int) -> list[dict]:
    """
    Every top-flight champion that later fell to the third tier or below:
    the title, the low point, how long it took, and the path since.
    """
    titles = collections.defaultdict(list)
    for cid, season in conn.execute(
            "SELECT club_id, season_end_year FROM standings WHERE tier = 1 AND status = 'Champions'"
            " AND club_id IS NOT NULL"):
        titles[cid].append(season)
    out = []
    for cid, years in titles.items():
        h = hist.get(cid, {})
        for title in sorted(years):
            after = sorted((s, t) for s, t in h.items() if s > title)
            low = max((t for _, t in after), default=1)
            if low < 3:
                continue
            reached = min(s for s, t in after if t >= 3)
            lowest_at = min(s for s, t in after if t == low)
            out.append({"club_id": cid, "title": title, "titles": sorted(years), "low": low,
                        "reached": reached, "years": reached - title, "lowest_at": lowest_at,
                        "now": h.get(latest), "path": [[s - title, h[s]] for s in sorted(h) if s >= title]})
            break       # the first title from which a club fell is the one that counts
    return sorted(out, key=lambda r: r["years"])


def relegations(hist: dict) -> list[dict]:
    """Every drop out of the top flight: the first season outside, and when (if ever) the club came back."""
    out = []
    for cid, h in hist.items():
        seasons = sorted(h)
        for prev, cur in zip(seasons, seasons[1:]):
            if h[prev] == 1 and h[cur] > 1 and cur == prev + 1:
                back = next((s for s in seasons if s > cur and h[s] == 1), None)
                out.append({"club_id": cid, "out": cur, "back": back,
                            "away": (back - cur) if back else None})
    return out


def return_odds(events: list[dict], latest: int, horizon: int = 25) -> list[dict]:
    """
    For k = 1..horizon seasons: the share back within k seasons, and - for
    those still away after k - the share that ever came back. Only
    relegations old enough to have run the k seasons count at k.
    """
    finished = latest - 1          # the season in progress cannot yet have ended a spell away
    rows = []
    for k in range(1, horizon + 1):
        seen = [e for e in events if finished - e["out"] + 1 >= k]
        within = [e for e in seen if e["away"] is not None and e["away"] <= k]
        still = [e for e in seen if e["away"] is None or e["away"] > k]
        later = [e for e in still if e["away"] is not None]
        rows.append({"k": k, "n": len(seen), "within": round(len(within) / len(seen), 3) if seen else None,
                     "still_n": len(still), "ever": round(len(later) / len(still), 3) if still else None})
    return rows


def chance_for(years_away: int, odds: list[dict], min_n: int = 15) -> dict | None:
    """The ever-return odds for a club this many seasons away, from the nearest k with enough clubs."""
    usable = [r for r in odds if r["still_n"] >= min_n and r["ever"] is not None]
    if not usable:
        return None
    best = min(usable, key=lambda r: abs(r["k"] - years_away))
    return {"chance": best["ever"], "n": best["still_n"], "k": best["k"]}


def fastest(hist: dict) -> dict:
    """The quickest falls from the top flight to the fourth tier, and the quickest climbs the other way."""
    def run(start_ok, end_ok, stop):
        best = {}
        for cid, h in hist.items():
            seasons = sorted(h)
            for i, s in enumerate(seasons):
                if not start_ok(h[s]):
                    continue
                for s2 in seasons[i + 1:]:
                    if stop(h[s2]):
                        break
                    if end_ok(h[s2]):
                        cand = {"club_id": cid, "from": s, "to": s2, "years": s2 - s,
                                "from_tier": h[s], "to_tier": h[s2]}
                        if cid not in best or cand["years"] < best[cid]["years"]:
                            best[cid] = cand
                        break
        return sorted(best.values(), key=lambda r: (r["years"], r["from"]))
    return {
        "falls": run(lambda t: t == 1, lambda t: t >= 4, lambda t: t == 1),
        "rises": run(lambda t: t >= 4, lambda t: t == 1, lambda t: False),
        "from_five": run(lambda t: t >= 5, lambda t: t == 1, lambda t: False),
    }


def risers(hist: dict, latest: int) -> list[dict]:
    """Clubs in the top two now that have been in the fourth tier or below since 1958/59."""
    out = []
    for cid, h in hist.items():
        now = h.get(latest)
        if now is None or now > 2:
            continue
        low = max(h.values())
        if low < 4:
            continue
        low_at = max(s for s, t in h.items() if t == low)          # the most recent time at the bottom
        peak_since = min(t for s, t in h.items() if s >= low_at)
        out.append({"club_id": cid, "low": low, "low_at": low_at, "now": now, "years": latest - low_at,
                    "climb": low - now, "top_flight_since": peak_since == 1})
    return sorted(out, key=lambda r: (-r["climb"], r["years"]))


def assemble(conn: sqlite3.Connection, with_size: bool = True) -> dict:
    hist = histories(conn)
    if not hist:
        return {}
    latest = max(s for h in hist.values() for s in h)
    names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))
    playing = {cid for cid, h in hist.items() if latest in h}

    def named(rows):
        return [dict(r, name=names.get(r["club_id"], r["club_id"])) for r in rows]

    events = relegations(hist)
    odds = return_odds(events, latest)

    # The fallen: top-flight history since 1958/59, playing now, in the third tier or below.
    fallen = []
    for cid in playing:
        h = hist[cid]
        tops = [s for s, t in h.items() if t == 1]
        if not tops or h[latest] < 3:
            continue
        last_top = max(tops)
        away = latest - last_top
        horizon = odds[-1]["k"] if odds else 0
        fallen.append({"club_id": cid, "top_seasons": len(tops), "last_top": last_top, "now": h[latest],
                       "away": away, "chance": chance_for(away, odds), "beyond": away > horizon,
                       "path": [[s, h[s]] for s in sorted(h)]})
    fallen.sort(key=lambda r: (-r["now"], r["last_top"]))

    # Live: where each fallen giant stands in its division this season.
    live = []
    rows = {r[0]: r[1:] for r in conn.execute(
        "SELECT club_id, position, played, points, division_name, tier FROM standings"
        " WHERE season_end_year = ? AND club_id IS NOT NULL", (latest,))}
    sizes = dict(conn.execute("SELECT division_name, COUNT(*) FROM standings WHERE season_end_year = ?"
                              " GROUP BY division_name", (latest,)))
    for f in fallen:
        r = rows.get(f["club_id"])
        if not r:
            continue
        pos, played, pts, div, tier = r
        n = sizes.get(div, 24)
        mood = ("climbing" if pos <= max(3, round(n * 0.25)) else
                "sinking" if pos > n - max(4, round(n * 0.2)) else "holding")
        live.append({"club_id": f["club_id"], "position": pos, "of": n, "played": played, "points": pts,
                     "division": div, "tier": tier, "mood": mood})
    live.sort(key=lambda r: (["climbing", "holding", "sinking"].index(r["mood"]), r["tier"], r["position"]))

    size = {"sleeping": [], "over": []}
    if with_size:
        try:
            import income
            clubs = [c for c in income.assemble(conn).get("clubs", []) if c["club_id"] not in WELSH]
            top_flight = {cid for cid, h in hist.items() if 1 in h.values()}
            ranked = sorted(clubs, key=lambda c: -c["residual"])
            size["sleeping"] = [dict(c, giant=c["club_id"] in top_flight) for c in ranked[:15] if c["residual"] > 0]
            size["over"] = [dict(c, giant=c["club_id"] in top_flight) for c in ranked[::-1][:15] if c["residual"] < 0]
            by = {c["club_id"]: c for c in clubs}
            for f in fallen:
                c = by.get(f["club_id"])
                f["predicted"] = c["predicted"] if c else None
        except Exception:      # no catchment model in this database: the page simply goes without
            pass

    fast = fastest(hist)
    return {
        "latest": latest,
        "champions": named(champions_fell(conn, hist, latest)),
        "odds": odds,
        "relegations": len(events),
        "exiles": named(sorted(({"club_id": e["club_id"], "out": e["out"], "back": e["back"], "away": e["away"]}
                                for e in events if e["away"]), key=lambda e: -e["away"])[:8]),
        "fallen": named(fallen),
        "live": named(live),
        "falls": named(fast["falls"][:10]),
        "rises": named(fast["rises"][:10]),
        "from_five": named(fast["from_five"][:5]),
        "risers": named(risers(hist, latest)),
        "sleeping": size["sleeping"],
        "over": size["over"],
    }
