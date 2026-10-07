"""
What moved this week: the lines on the home page.

Each recipe reads the season in progress and returns candidates - a tag,
a sentence with the numbers in it, and the page that explains it. There
are more candidates than the page has room for; pick() keeps the most
unusual ones, no more than two to a tag, so a quiet week in February does
not read like week ten in October. Everything is computed, nothing is
written down, and two builds of the same database give the same lines.

The hero is one sentence in the voice of docs/voice.md: a club's grand
past, then its present, and the distance between them does the work.
A champion now in the third tier or below is the first choice; failing
that, the former top-flight club with the most seasons up there.
"""

import sqlite3

import giants as giants_mod
import level as level_mod
import luck as luck_mod
import yoyo as yoyo_mod

ORDINALS = ["", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
            "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
            "eighteenth", "nineteenth", "twentieth", "twenty-first", "twenty-second", "twenty-third",
            "twenty-fourth"]
WORDS = ["nought", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
STREAK_WORDS = {"win": "have won", "unbeaten": "are unbeaten in", "clean_sheet": "have kept a clean sheet in",
                "loss": "have lost", "winless": "have not won in", "draw": "have drawn", "scoreless": "have not scored in"}


def ordinal(n: int) -> str:
    return ORDINALS[n] if 0 < n < len(ORDINALS) else f"{n}th"


def word(n: int) -> str:
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def season_label(y: int) -> str:
    return f"{y - 1}/{y % 100:02d}"


def _div(name: str) -> str:
    """'the Premier League' but bare 'League One', as the editions say it."""
    return name if name.startswith(("League", "Step", "National League North", "National League South")) else f"the {name}"


def _table(conn: sqlite3.Connection, season: int) -> dict[str, dict]:
    """Every club's row this season, with the size of its division."""
    rows = {}
    cols = {r[1] for r in conn.execute("PRAGMA table_info(standings)")}
    deducted = "s.points_deducted" if "points_deducted" in cols else "0"
    sizes = dict(conn.execute("SELECT division_name, COUNT(*) FROM standings WHERE season_end_year = ?"
                              " GROUP BY division_name", (season,)))
    for r in conn.execute(
            "SELECT s.club_id, COALESCE(m.canonical_name, s.club_name), s.division_name, s.tier, s.position,"
            f" s.played, s.won, s.drawn, s.lost, s.gd, s.points, {deducted}"
            " FROM standings s LEFT JOIN club_master m ON m.club_id = s.club_id"
            " WHERE s.season_end_year = ? AND s.club_id IS NOT NULL", (season,)):
        rows[r[0]] = {"club_id": r[0], "name": r[1], "division": r[2], "tier": r[3], "position": r[4],
                      "played": r[5] or 0, "won": r[6] or 0, "drawn": r[7] or 0, "lost": r[8] or 0,
                      "gd": r[9] or 0, "points": r[10] or 0, "deducted": r[11] or 0, "of": sizes.get(r[2], 0)}
    return rows


def _line(tag, text, to, path, weight, club_id=None, slug=None):
    return {"tag": tag, "text": text, "to": to, "path": path, "weight": round(weight, 2),
            "club_id": club_id, "slug": slug}


# ── Recipes ───────────────────────────────────────────────────────────────

def luck_lines(conn, season, table) -> list[dict]:
    """The luckiest and unluckiest start in each division that has odds."""
    try:
        by = luck_mod.current(conn, season)
    except Exception:
        return []
    out = []
    divisions = sorted({(r["tier"], r["division"]) for r in table.values()})
    for tier, div in divisions:
        rows = [dict(r, luck=by[c]["luck_o"], exp=by[c]["xo"]) for c, r in table.items()
                if r["division"] == div and by.get(c, {}).get("luck_o") is not None]
        if len(rows) < 4:
            continue
        rows.sort(key=lambda r: -r["luck"])
        a, b = rows[0], rows[-1]
        text = (f"{a['name']} have <b>{a['points']} points</b> from {a['played']}; the odds said {a['exp']:.1f}. "
                f"{b['name']} have {b['points']}; the odds said {b['exp']:.1f}.")
        # Early luck is noise: a five-game swing counts for less than a fifteen-game one.
        weight = (abs(a["luck"]) + abs(b["luck"])) * min(1.0, a["played"] / 12)
        # Two clubs in one line, so it claims neither: a club can still carry its own line below.
        out.append(_line("Luck", text, f"Luck → this season, {div}",
                         f"insights/luck/index.html#s={season}&t={tier}&m=o", weight, None, "luck"))
    return out


def giants_lines(conn, season, table) -> list[dict]:
    """Where the fallen giants stand: who is climbing and who is sinking."""
    try:
        d = giants_mod.assemble(conn, with_size=False)
    except Exception:
        return []
    live = d.get("live") or []
    up = [r for r in live if r["mood"] == "climbing"]
    down = [r for r in live if r["mood"] == "sinking" and r["position"] <= r["of"]]
    if not up and not down:
        return []
    parts = []
    if up:
        names = _join([r["name"] for r in up[:3]])
        parts.append(f"{names} {'are' if len(up[:3]) > 1 else 'is'} in the top quarter of "
                     f"{_div(up[0]['division'])}.")
    if down:
        w = max(down, key=lambda r: (r["position"] / max(1, r["of"]), r["tier"]))
        parts.append(f"{w['name']} are <b>{ordinal(w['position'])} of {w['of']}</b> in {_div(w['division'])}.")
    return [_line("Giants", " ".join(parts), "Fallen giants → the giants this season",
                  "insights/fallen-giants/index.html#live", 3 + 0.7 * (len(up) + len(down)),
                  (down[-1] if down else up[0])["club_id"], "fallen-giants")]


def yoyo_lines(conn, season, table) -> list[dict]:
    """The longest bounce still running."""
    try:
        d = yoyo_mod.assemble(conn)
    except Exception:
        return []
    out = []
    for c in (d.get("active") or [])[:3]:
        run = c.get("active") or {}
        if run.get("length", 0) < 3 or c["club_id"] not in table:
            continue
        r = table[c["club_id"]]
        moves = ", ".join("relegated" if ch == "R" else "promoted" for ch in run["pattern"])
        text = (f"{c['name']}: {moves}. <b>{word(run['length']).capitalize()} seasons running.</b> "
                f"{ordinal(r['position']).capitalize()} in {_div(r['division'])}, "
                f"{r['points']} points from {r['played']}.")
        out.append(_line("Yo-yo", text, "Yo-yo clubs → bouncing right now", "insights/yo-yo/index.html#now",
                         1.5 * run["length"], c["club_id"], "yo-yo"))
    return out


def record_lines(conn, season, table) -> list[dict]:
    """A current streak within one match of the club record."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(club_streak_records)")}
    if "current_length" not in cols:
        return []
    out = []
    # A streak counts only if its last match is this season: the table keeps
    # the last streak of a club whose matches stopped coming years ago.
    for cid, kind, rec_len, rec_season, cur in conn.execute(
            "SELECT club_id, streak_type, record_length, record_season_end_year, current_length"
            " FROM club_streak_records WHERE current_length >= 5 AND current_length >= record_length - 1"
            " AND current_last_date >= ?", (f"{season - 1}-06-01",)):
        r = table.get(cid)
        if not r or kind not in STREAK_WORDS:
            continue
        rel = ("level with" if cur == rec_len else "one short of" if cur < rec_len else "past")
        text = (f"{r['name']} {STREAK_WORDS[kind]} <b>{cur}</b>, {rel} the club record"
                f"{' set in ' + season_label(rec_season) if cur <= rec_len else ''}. "
                f"{ordinal(r['position']).capitalize()} in {_div(r['division'])}, {r['points']} from {r['played']}.")
        out.append(_line("Record", text, "Records → the streaks", "insights/records/index.html",
                         cur / 2 + (3 if cur >= rec_len else 0), cid, "records"))
    return out


def level_lines(conn, season, table) -> list[dict]:
    """Clubs two or more divisions from where their own history puts them."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(club_trajectory)")}
    if "natural_level_gap" not in cols:
        return []
    out = []
    for cid, nl, gap in conn.execute(
            "SELECT club_id, natural_level_tier, natural_level_gap FROM club_trajectory"
            " WHERE natural_level_gap IS NOT NULL AND ABS(natural_level_gap) >= 2"):
        r = table.get(cid)
        if not r or nl is None:
            continue
        where = "below" if gap > 0 else "above"
        text = (f"{r['name']} are a {level_mod.bucket_name(nl)} club by their own history. They are "
                f"{ordinal(r['position'])} in {_div(r['division'])}, <b>{word(abs(gap))} divisions {where}</b> it.")
        out.append(_line("Level", text, "Above and below their level", "insights/natural-level/index.html",
                         2 * abs(gap) + (0.5 if gap > 0 else 0), cid, "natural-level"))
    return out


def deduction_lines(conn, season, table) -> list[dict]:
    out = []
    for r in table.values():
        if not r["deducted"]:
            continue
        would = sorted((x for x in table.values() if x["division"] == r["division"]),
                       key=lambda x: (-(x["points"] + (x["deducted"] if x is r else 0)), -x["gd"]))
        place = next(i for i, x in enumerate(would, 1) if x is r)
        text = (f"{r['name']} have been docked <b>{r['deducted']} points</b>. They are {ordinal(r['position'])} "
                f"in {_div(r['division'])}; without the deduction they would be {ordinal(place)}.")
        out.append(_line("Docked", text, "Clubs docked points", "themes/points-deductions/index.html",
                         3 + r["deducted"] / 3, r["club_id"], "points-deductions"))
    return out


def movement_lines(conn, season, table) -> list[dict]:
    """Two moves the same way in two seasons, and where the club is now."""
    hist = giants_mod.histories(conn)
    out = []
    for cid, r in table.items():
        h = hist.get(cid, {})
        if not all(s in h for s in (season - 2, season - 1, season)):
            continue
        a, b, c = h[season - 2], h[season - 1], h[season]
        if a > b > c:
            text = (f"{r['name']}: promoted twice in two seasons. <b>{ordinal(r['position']).capitalize()}</b> in "
                    f"{_div(r['division'])}, {r['points']} points from {r['played']}.")
            safe = r["position"] <= r["of"] - 4
            out.append(_line("Rise", text, "The rise → did they hold on", "insights/the-rise/index.html",
                             4 + (1.5 if safe else 0) + (a - c), cid, "the-rise"))
        elif a < b < c:
            text = (f"{r['name']}: relegated twice in two seasons. <b>{ordinal(r['position']).capitalize()} of "
                    f"{r['of']}</b> in {_div(r['division'])}.")
            out.append(_line("Drop", text, "The drop → does it stop", "insights/the-drop/index.html",
                             4 + (c - a) + (1.5 if r["position"] > r["of"] - 4 else 0), cid, "the-drop"))
    return out


def bottom_lines(conn, season, table) -> list[dict]:
    """Lost the lot, or not won yet, well into the season."""
    out = []
    for r in table.values():
        if r["played"] < 6 or r["won"]:
            continue
        if not r["drawn"]:
            text = (f"{r['name']} have lost all <b>{word(r['played'])}</b>. Goal difference "
                    f"{'minus ' + str(-r['gd']) if r['gd'] < 0 else r['gd']}. Bottom of {_div(r['division'])}.")
            weight = 2 + r["played"] * 0.6
        else:
            text = (f"{r['name']} have not won in <b>{word(r['played'])}</b>. "
                    f"{ordinal(r['position']).capitalize()} of {r['of']} in {_div(r['division'])}.")
            weight = 1 + r["played"] * 0.4
        out.append(_line("Drop", text, "Safe thresholds → what it takes to stay up",
                         "insights/safe-thresholds/index.html", weight, r["club_id"], "safe-thresholds"))
    return out


RECIPES = (luck_lines, giants_lines, yoyo_lines, record_lines, level_lines, deduction_lines,
           movement_lines, bottom_lines)


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def candidates(conn: sqlite3.Connection, season: int) -> list[dict]:
    table = _table(conn, season)
    if not table:
        return []
    out = []
    for recipe in RECIPES:
        try:
            out.extend(recipe(conn, season, table))
        except sqlite3.Error:
            continue
    return out


def pick(cands: list[dict], built: set[str] | None = None, limit: int = 8, per_tag: int = 2,
         exclude: str | None = None) -> list[dict]:
    """
    The most unusual lines first, at most two to a tag and one to a club,
    never the hero's club, and never a line that points at a page this
    build did not make. Ties break on the text, so the order never depends
    on dict order.
    """
    out, tags, clubs = [], {}, {exclude}
    for c in sorted(cands, key=lambda c: (-c["weight"], c["text"])):
        if built is not None and c["slug"] not in built:
            continue
        if tags.get(c["tag"], 0) >= per_tag or (c["club_id"] and c["club_id"] in clubs):
            continue
        out.append(c)
        tags[c["tag"]] = tags.get(c["tag"], 0) + 1
        clubs.add(c["club_id"])
        if len(out) >= limit:
            break
    return out


def by_slug(cands: list[dict]) -> dict[str, dict]:
    """The strongest line for each page, for the story index's tiles."""
    best: dict[str, dict] = {}
    for c in sorted(cands, key=lambda c: (-c["weight"], c["text"])):
        best.setdefault(c["slug"], c)
    return best


# ── The hero ──────────────────────────────────────────────────────────────

def hero(conn: sqlite3.Connection, season: int) -> dict | None:
    table = _table(conn, season)
    if not table:
        return None
    try:
        d = giants_mod.assemble(conn, with_size=False)
    except Exception:
        return None
    hist = giants_mod.histories(conn)
    champs = [c for c in d.get("champions", []) if (c.get("now") or 0) >= 3 and c["club_id"] in table]
    if champs:
        c = max(champs, key=lambda c: (c["now"], c["title"]))
        r = table[c["club_id"]]
        start = c["title"]
        past = f"Champions of England, {season_label(c['title'])}."
        fastest = d["champions"][0]
        runner = d["champions"][1] if len(d["champions"]) > 1 else None
        sub = (f"The fastest fall from the title to the third tier in the record: {word(fastest['years'])} years"
               f"{'. ' + runner['name'] + ' held it at ' + word(runner['years']) if runner else ''}."
               if fastest["club_id"] == c["club_id"] else
               f"{word(c['years']).capitalize()} years from the title to the third tier; "
               f"{fastest['name']} did it in {word(fastest['years'])}.")
        path, to = "insights/fallen-giants/index.html#champions", "From champions to the third tier"
    else:
        fallen = [f for f in d.get("fallen", []) if f["club_id"] in table]
        if not fallen:
            return None
        c = max(fallen, key=lambda f: (f["top_seasons"], -f["last_top"]))
        r = table[c["club_id"]]
        start = max(1, c["last_top"] - 10)
        past = (f"{word(c['top_seasons']).capitalize()} season{'s' if c['top_seasons'] != 1 else ''} in the "
                f"top flight, the last {season_label(c['last_top'])}.")
        sub = f"Away {word(c['away'])} seasons. "
        if c.get("chance"):
            sub += (f"Of clubs away that long, {c['chance']['chance'] * 100:.0f}% came back.")
        path, to = "insights/fallen-giants/index.html#fallen", "Every fallen giant"
    h = hist.get(c["club_id"], {})
    path_points = [(s, h[s]) for s in sorted(h) if s >= start]
    colours = (None, None)
    if "color_primary" in {r[1] for r in conn.execute("PRAGMA table_info(club_master)")}:
        colours = conn.execute("SELECT color_primary, color_secondary FROM club_master WHERE club_id = ?",
                               (c["club_id"],)).fetchone() or colours
    return {
        "club_id": c["club_id"], "name": c["name"],
        "past": past,
        "present": f"{ordinal(r['position']).capitalize()} in {_div(r['division'])}.",
        "sub": sub, "to": to, "path": path,
        "points": path_points, "first": start, "latest": season,
        "colour": colours[0], "colour2": colours[1],
        "form": _form(conn, season, c["club_id"]), "points_now": r["points"], "played": r["played"],
    }


def _form(conn, season, cid, n=6) -> str:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    if "home_club_id" not in cols:
        return ""
    rows = conn.execute(
        "SELECT home_club_id, fthg, ftag FROM matches WHERE season_end_year = ?"
        " AND (home_club_id = ? OR away_club_id = ?) AND fthg IS NOT NULL ORDER BY match_date DESC LIMIT ?",
        (season, cid, cid, n)).fetchall()
    out = []
    for home, hg, ag in reversed(rows):
        mine, theirs = (hg, ag) if home == cid else (ag, hg)
        out.append("W" if mine > theirs else "D" if mine == theirs else "L")
    return "".join(out)


def sparkline(points: list[tuple[int, int]], first: int, latest: int, max_tier: int = 7,
              w: int = 260, h: int = 90) -> dict:
    """Coordinates for the hero's tier line: x by season, y by tier, one to max_tier."""
    span = max(1, latest - first)
    tiers = max(3, max((t for _, t in points), default=1))

    def x(s):
        return round(20 + (s - first) / span * (w - 30), 1)

    def y(t):
        return round(14 + (t - 1) / max(1, tiers - 1) * (h - 40), 1)

    return {"w": w, "h": h, "tiers": tiers,
            "line": " ".join(f"{x(s)},{y(t)}" for s, t in points),
            "grid": [(t, y(t)) for t in range(1, tiers + 1)],
            "start": (x(points[0][0]), y(points[0][1])) if points else None,
            "end": (x(points[-1][0]), y(points[-1][1])) if points else None}

