"""
Yo-yo clubs: the ones that cannot sit still, measured three ways.

    bounce run     promoted, relegated, promoted again - in consecutive
                   seasons, with no season of staying put between. The
                   longest such run is the purest kind of yo-yo: Rotherham's
                   six seasons from 2016/17 are the record.
    moves          promotions plus relegations per finished season, over
                   at least MIN_SEASONS seasons. The old page's score, with
                   the one-season clubs that used to top it ruled out.
    restlessness   the tiers a club has spanned multiplied by its moves per
                   season. A club that bounces between two divisions and a
                   club that has fallen from the top flight to the fifth
                   tier and climbed back both score here, for different
                   reasons.

Then the elastic itself: at each boundary between two tiers, how often a
club that crosses it is sent straight back the next season, and how that
has changed by decade. The crossings themselves are set by the rules -
three up, three down - so counting them says nothing; the reversals are
where the money shows.

Statuses come from standings as trajectory.py and movement.py read them:
a top-flight "Champions" is a title, not a promotion.
"""

import sqlite3
from collections import Counter, defaultdict

import movement

MIN_SEASONS = 15
WINDOW = 6          # seasons over which a fall or climb is measured
TOP = 25            # clubs on the seismograph per measure
BOUNDARY_LABELS = {
    (1, 2): "Top flight / second tier", (2, 3): "Second / third", (3, 4): "Third / fourth",
    (4, 5): "Fourth / fifth", (5, 6): "Fifth / sixth", (6, 7): "Sixth / seventh",
}


def kind(tier: int, status: str) -> str:
    """'P', 'R', 'S' (stayed) or '?' (in progress, or an unknown status)."""
    if status == "In progress":
        return "?"
    k = movement.classify(tier, status)
    return {"promotion": "P", "relegation": "R", "stay": "S"}.get(k, "?")


def histories(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    """{club_id: [(season, tier, status, division, position), ...]} oldest first."""
    out: dict[str, list[tuple]] = defaultdict(list)
    for row in conn.execute(
            "SELECT club_id, season_end_year, tier, status, division_name, position FROM standings"
            " WHERE club_id IS NOT NULL ORDER BY club_id, season_end_year"):
        out[row[0]].append(tuple(row[1:]))
    return dict(out)


def bounce_runs(h: list[tuple]) -> list[dict]:
    """
    Every alternating run of two or more moves in consecutive seasons:
    [{"start", "end", "length", "pattern": "RPRP"}]. A season in progress
    ends the search but does not count.
    """
    runs = []
    cur: list[tuple] = []
    for season, tier, status, *_ in h:
        k = kind(tier, status)
        if k in ("P", "R") and cur and cur[-1][1] != k and cur[-1][0] == season - 1:
            cur.append((season, k))
        elif k in ("P", "R"):
            if len(cur) >= 2:
                runs.append(cur)
            cur = [(season, k)]
        else:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
    if len(cur) >= 2:
        runs.append(cur)
    return [{"start": r[0][0], "end": r[-1][0], "length": len(r), "pattern": "".join(k for _, k in r)}
            for r in runs]


def active_run(h: list[tuple], latest_finished: int) -> dict | None:
    """The run still alive: it ends at the latest finished season and the next is in progress."""
    if not h or h[-1][2] != "In progress" or h[-1][0] != latest_finished + 1:
        return None
    for r in bounce_runs(h):
        if r["end"] == latest_finished:
            return r
    return None


def measures(h: list[tuple]) -> dict:
    """Moves, finished seasons, moves per season, tiers spanned and restlessness."""
    fin = [x for x in h if x[2] != "In progress"]
    moves = sum(1 for x in fin if kind(x[1], x[2]) in ("P", "R"))
    tiers = [x[1] for x in fin]
    amp = (max(tiers) - min(tiers)) if tiers else 0
    n = len(fin)
    mps = moves / n if n else 0.0
    return {"moves": moves, "seasons": n, "mps": round(mps, 3), "amplitude": amp,
            "restlessness": round(amp * mps, 3),
            "promotions": sum(1 for x in fin if kind(x[1], x[2]) == "P"),
            "relegations": sum(1 for x in fin if kind(x[1], x[2]) == "R")}


def fastest(h: list[tuple], window: int = WINDOW) -> dict:
    """The biggest fall and climb, in tiers, over at most `window` seasons."""
    pts = [(s, t) for s, t, st, *_ in h if st != "In progress"]
    fall = climb = (0, None, None)

    def better(new, old):  # more tiers, or the same number in fewer seasons
        return new[0] > old[0] or (new[0] == old[0] and new[0] and new[2] - new[1] < old[2] - old[1])

    for i, (s1, t1) in enumerate(pts):
        for s2, t2 in pts[i + 1:]:
            if s2 - s1 > window:
                break
            if better((t2 - t1, s1, s2), fall):
                fall = (t2 - t1, s1, s2)
            if better((t1 - t2, s1, s2), climb):
                climb = (t1 - t2, s1, s2)
    return {"fall": fall, "climb": climb}


def round_trip(h: list[tuple]) -> tuple[int, int | None, int | None, int | None]:
    """
    The deepest fall that was climbed back: (tiers, peak season, trough
    season, return season), where the club was at least that many tiers
    higher both before and after the trough.
    """
    pts = [(s, t) for s, t, st, *_ in h if st != "In progress"]
    best = (0, None, None, None)
    for j, (s_tr, t_tr) in enumerate(pts):
        before = [(t, s) for s, t in pts[:j]]
        after = [(t, s) for s, t in pts[j + 1:]]
        if not before or not after:
            continue
        hb = min(t for t, _ in before)
        sb = max(s for t, s in before if t == hb)   # the last time it was that high before the fall
        ha = min(t for t, _ in after)
        sa = min(s for t, s in after if t == ha)    # the first time it got back there
        depth = min(t_tr - hb, t_tr - ha)
        if depth > best[0]:
            best = (depth, sb, s_tr, sa)
    return best


def elastic(hists: dict[str, list[tuple]]) -> dict:
    """
    For each boundary and decade: crossings, and how many were reversed
    the very next season. Also the bounce-back and straight-back-down
    rates by tier, since "relegated from the top flight" and "promoted to
    it" are the two halves of the same elastic.
    """
    cross: dict[tuple, Counter] = defaultdict(Counter)      # (lo, hi) -> {"n", "back", decade n/back}
    by_tier: dict[str, dict[int, Counter]] = {"relegated": defaultdict(Counter), "promoted": defaultdict(Counter)}
    for h in hists.values():
        by_season = {x[0]: x for x in h}
        for season, tier, status, *_ in h:
            k = kind(tier, status)
            if k not in ("P", "R"):
                continue
            nxt = by_season.get(season + 1)
            if not nxt or nxt[2] == "In progress":
                continue
            nk = kind(nxt[1], nxt[2])
            reversed_ = (k == "R" and nk == "P") or (k == "P" and nk == "R")
            lo, hi = (tier, nxt[1]) if k == "R" else (nxt[1], tier)
            if hi - lo != 1:
                continue  # an administrative drop of two tiers is not a bounce
            decade = season // 10 * 10
            c = cross[(lo, hi)]
            c["n"] += 1
            c[f"n{decade}"] += 1
            if reversed_:
                c["back"] += 1
                c[f"back{decade}"] += 1
            side = "relegated" if k == "R" else "promoted"
            by_tier[side][tier]["n"] += 1
            by_tier[side][tier][f"n{decade}"] += 1
            if reversed_:
                by_tier[side][tier]["back"] += 1
                by_tier[side][tier][f"back{decade}"] += 1
    return {"boundaries": {k: dict(v) for k, v in cross.items()},
            "by_tier": {s: {t: dict(c) for t, c in d.items()} for s, d in by_tier.items()}}


def assemble(conn: sqlite3.Connection) -> dict:
    """Everything the page draws."""
    names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))
    hists = histories(conn)
    seasons = sorted({x[0] for h in hists.values() for x in h})
    if not seasons:
        return {}
    newest = seasons[-1]
    latest_finished = max((x[0] for h in hists.values() for x in h if x[2] != "In progress"), default=newest)

    clubs = []
    for cid, h in hists.items():
        m = measures(h)
        runs = bounce_runs(h)
        longest = max(runs, key=lambda r: (r["length"], r["end"]), default=None)
        clubs.append({
            "club_id": cid, "name": names.get(cid, cid), **m,
            "runs": runs, "longest": longest, "run": longest["length"] if longest else 0,
            "active": active_run(h, latest_finished),
            "fastest": fastest(h), "round_trip": round_trip(h),
            "history": h, "ranked": m["seasons"] >= MIN_SEASONS,
            "now": h[-1] if h[-1][0] == newest else None,
        })

    ranked = [c for c in clubs if c["ranked"]]
    leaders = {
        "run": sorted(ranked, key=lambda c: (-c["run"], -(c["longest"]["end"] if c["longest"] else 0), c["name"])),
        "mps": sorted(ranked, key=lambda c: (-c["mps"], -c["moves"], c["name"])),
        "restlessness": sorted(ranked, key=lambda c: (-c["restlessness"], -c["amplitude"], c["name"])),
    }
    for key, rows in leaders.items():
        for i, c in enumerate(rows, start=1):
            c.setdefault("rank", {})[key] = i
    shown = {c["club_id"] for rows in leaders.values() for c in rows[:TOP]}
    active = sorted((c for c in clubs if c["active"] and c["active"]["length"] >= 2),
                    key=lambda c: (-c["active"]["length"], c["name"]))
    hall = {
        "runs": sorted((c for c in clubs if c["run"] >= 4), key=lambda c: (-c["run"], -c["longest"]["end"]))[:12],
        "falls": sorted((c for c in clubs if c["fastest"]["fall"][0] >= 3),
                        key=lambda c: (-c["fastest"]["fall"][0], c["fastest"]["fall"][2] - c["fastest"]["fall"][1], c["name"]))[:10],
        "climbs": sorted((c for c in clubs if c["fastest"]["climb"][0] >= 3),
                         key=lambda c: (-c["fastest"]["climb"][0], c["fastest"]["climb"][2] - c["fastest"]["climb"][1], c["name"]))[:10],
        "round_trips": sorted((c for c in clubs if c["round_trip"][0] >= 3),
                              key=lambda c: (-c["round_trip"][0], c["name"]))[:10],
    }
    return {
        "seasons": seasons, "newest": newest, "latest_finished": latest_finished,
        "clubs": clubs, "leaders": leaders, "shown": shown, "active": active,
        "hall": hall, "elastic": elastic(hists), "min_seasons": MIN_SEASONS,
        "ranked_count": len(ranked),
    }
