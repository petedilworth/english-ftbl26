"""
The reviews: Monday for tiers 1 and 2, Tuesday for tiers 3 to 5.

Each covers everything in its tiers since the previous review - seven
days - which is how Tuesday picks up the previous midweek without a
special case. In order: the reckoning against Friday's claims, the
results that moved history (from result_bands), the score grid with a
tag and a movement column, the streak watch, and one alternate table.

The facts layer. Words are in templates/email/review.html and
editions/phrasing.py.
"""

import datetime
import logging
import sqlite3
from pathlib import Path

import charts
import fixtures as fixtures_mod
from editions import archive, config, phrasing, render
from editions.base import Edition, EditionOutput
from editions.preview import TIER_NAMES

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7
# The results file can lag the weekend by a day or two, so a Sunday game
# may not be on file when Monday's review builds. Each review records the
# results it covered, and the next one looks this far back for anything
# nobody has covered yet.
CATCH_UP_DAYS = 14
BAND_RANK = {"historic": 0, "notable": 1, "of_note": 2}
# Within a band: the result itself before what it did to a run or a start.
KIND_RANK = {"margin": 0, "opponent": 1, "streak": 2, "start": 3}
PROSE_BANDS = ("historic", "notable")
CHART_COUNT = 2

# Which alternate table this week: rotates on the ISO week number.
ALT_TABLES = ("home", "away", "form")
FORM_GAMES = 6

# Streak watch: a live run is worth a line when it is within two of the
# club's record, and the record is long enough for that to mean anything.
STREAK_RECORD_MIN = 4
STREAK_CURRENT_MIN = 2


def _placeholders(items) -> str:
    return ",".join("?" * len(items))


def names_for(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))


def result_key(r: dict) -> str:
    return f"{r['date'].isoformat()}|{r['home_id']}|{r['away_id']}"


def covered_keys(edition: str) -> tuple[set[str], bool]:
    """
    Every result a previous edition of this review has already carried,
    and whether there was a previous edition at all - the first review
    ever has nothing to catch up on, and must not carry the fortnight
    before it existed.
    """
    keys: set[str] = set()
    docs = archive.all_claims(edition)
    for doc in docs:
        keys.update(doc.get("covered") or [])
    return keys, bool(docs)


def results_in_window(conn: sqlite3.Connection, tiers: tuple[int, ...],
                      start: datetime.date, end: datetime.date) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT match_date, tier, home_club_id, away_club_id, home_name, away_name, fthg, ftag
        FROM matches
        WHERE match_date BETWEEN ? AND ? AND tier IN ({_placeholders(tiers)})
          AND fthg IS NOT NULL
        ORDER BY tier, match_date, home_name
        """,
        (start.isoformat(), end.isoformat(), *tiers),
    ).fetchall()
    return [
        {"date": datetime.date.fromisoformat(d), "tier": t, "division_name": TIER_NAMES.get(t, f"Tier {t}"),
         "home_id": h, "away_id": a, "home": hn, "away": an, "hg": int(hg), "ag": int(ag),
         "bands": []}
        for d, t, h, a, hn, an, hg, ag in rows
    ]


def current_table(conn: sqlite3.Connection, season: int,
                  tiers: tuple[int, ...]) -> dict[str, dict]:
    return {
        club_id: {"tier": tier, "position": pos, "points": pts, "played": played}
        for club_id, tier, pos, pts, played in conn.execute(
            f"SELECT club_id, tier, position, points, played FROM standings"
            f" WHERE season_end_year = ? AND tier IN ({_placeholders(tiers)})",
            (season, *tiers))
    }


def bands_in_window(conn: sqlite3.Connection, tiers: tuple[int, ...],
                    start: datetime.date, end: datetime.date) -> list[dict]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='result_bands'").fetchone():
        return []
    import json
    rows = conn.execute(
        f"""
        SELECT match_date, home_club_id, away_club_id, club_id, kind, band, since_season, detail
        FROM result_bands
        WHERE match_date BETWEEN ? AND ? AND tier IN ({_placeholders(tiers)})
        """,
        (start.isoformat(), end.isoformat(), *tiers),
    ).fetchall()
    return [
        {"date": d, "home_id": h, "away_id": a, "club_id": c, "kind": k, "band": b,
         "since": since, "detail": json.loads(detail or "{}")}
        for d, h, a, c, k, b, since, detail in rows
    ]


def streak_watch(conn: sqlite3.Connection, tiers: tuple[int, ...], season: int,
                 start: datetime.date) -> list[dict]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='club_streak_records'").fetchone():
        return []
    rows = conn.execute(
        f"""
        SELECT r.club_id, r.streak_type, r.current_length, r.record_length,
               r.record_season_end_year, r.current_start_date, s.tier
        FROM club_streak_records r
        JOIN standings s ON s.club_id = r.club_id AND s.season_end_year = ?
        WHERE s.tier IN ({_placeholders(tiers)})
          AND r.current_last_date >= ?
          AND r.record_length >= ? AND r.current_length >= ?
          AND r.current_length >= r.record_length - 2
        ORDER BY r.current_length DESC, r.club_id
        """,
        (season, *tiers, start.isoformat(), STREAK_RECORD_MIN, STREAK_CURRENT_MIN),
    ).fetchall()
    return [
        {"club_id": c, "streak_type": t, "current": cur, "record": rec,
         "record_season": rs, "since": since, "tier": tier}
        for c, t, cur, rec, rs, since, tier in rows
    ]


def alternate_table(conn: sqlite3.Connection, season: int, tier: int, kind: str,
                    names: dict[str, str]) -> list[dict]:
    """Home-only, away-only, or last-six form; 3-1-0, sorted like a table."""
    rows = conn.execute(
        """
        SELECT match_date, home_club_id, away_club_id, fthg, ftag FROM matches
        WHERE season_end_year = ? AND tier = ? AND match_date IS NOT NULL
        ORDER BY match_date
        """,
        (season, tier),
    ).fetchall()
    per_club: dict[str, list[tuple[int, int]]] = {}
    for _, h, a, hg, ag in rows:
        if h:
            per_club.setdefault(h, [])
            if kind != "away":
                per_club[h].append((int(hg), int(ag)))
        if a:
            per_club.setdefault(a, [])
            if kind != "home":
                per_club[a].append((int(ag), int(hg)))
    table = []
    for club_id, games in per_club.items():
        if kind == "form":
            games = games[-FORM_GAMES:]
        w = sum(1 for gf, ga in games if gf > ga)
        d = sum(1 for gf, ga in games if gf == ga)
        gf = sum(g for g, _ in games)
        ga = sum(g for _, g in games)
        table.append({"club_id": club_id, "name": names.get(club_id, club_id),
                      "played": len(games), "won": w, "drawn": d, "lost": len(games) - w - d,
                      "gd": gf - ga, "points": 3 * w + d})
    table.sort(key=lambda r: (-r["points"], -r["gd"], r["name"]))
    for n, r in enumerate(table, start=1):
        r["position"] = n
    return table


def _movement(club_id: str, before: dict, now: dict) -> int | None:
    b, n = before.get(club_id), now.get(club_id)
    if not b or not n or b.get("tier") != n.get("tier") or not b.get("position") or not n.get("position"):
        return None
    return b["position"] - n["position"]


class ReviewEdition(Edition):
    tiers: tuple[int, ...] = ()
    label = ""

    def build(self) -> EditionOutput:
        conn, date = self.conn, self.date
        start, end = date - datetime.timedelta(days=WINDOW_DAYS), date - datetime.timedelta(days=1)
        season = fixtures_mod.current_season_end_year(date)
        names = names_for(conn)

        # This week's results, plus anything older that no review has
        # carried - a result that reached the file after its review built.
        already, has_previous = covered_keys(self.name)
        lookback = date - datetime.timedelta(days=CATCH_UP_DAYS) if has_previous else start
        results = []
        for r in results_in_window(conn, self.tiers, lookback, end):
            r["late"] = r["date"] < start
            if not r["late"] or result_key(r) not in already:
                results.append(r)
        by_pair = {(r["home_id"], r["away_id"]): r for r in results}
        for band in bands_in_window(conn, self.tiers, lookback, end):
            r = by_pair.get((band["home_id"], band["away_id"]))
            if r is not None:
                r["bands"].append(band)
        for r in results:
            r["bands"].sort(key=lambda b: (BAND_RANK[b["band"]], KIND_RANK.get(b["kind"], 9)))

        claims_doc = archive.find_claims("preview", start, end)
        before = (claims_doc or {}).get("table") or {}
        now = current_table(conn, season, self.tiers)
        for r in results:
            r["home_move"] = _movement(r["home_id"], before, now)
            r["away_move"] = _movement(r["away_id"], before, now)
            r["tag"] = phrasing.band_tag(r["bands"][0], names) if r["bands"] else ""

        # The reckoning: Friday's picks in these tiers, and what came of them.
        reckoning = []
        for claim in (claims_doc or {}).get("claims", []):
            f = claim["fixture"]
            if f.get("tier") not in self.tiers:
                continue
            # A pick dated after this window is the next review's to answer.
            if f.get("date") and datetime.date.fromisoformat(f["date"]) > end:
                continue
            r = by_pair.get((f["home_id"], f["away_id"]))
            reckoning.append({
                "claim": claim, "result": r,
                "text": phrasing.reckoning(claim, r, now, names),
            })

        history = [r for r in results if r["bands"] and r["bands"][0]["band"] in PROSE_BANDS]
        history.sort(key=lambda r: (BAND_RANK[r["bands"][0]["band"]], r["date"]))
        for r in history:
            r["prose"] = [phrasing.band_sentence(b, names) for b in r["bands"]
                          if b["band"] in PROSE_BANDS]

        images: list[tuple[Path, str]] = []
        for n, r in enumerate(history[:CHART_COUNT]):
            cid = f"chart-{n}"
            path = charts.fixture_chart(conn, r["home_id"], r["away_id"],
                                        names.get(r["home_id"], r["home"]),
                                        names.get(r["away_id"], r["away"]),
                                        self.chart_dir / f"{cid}.png")
            if path:
                r["cid"] = cid
                images.append((path, cid))

        streaks = streak_watch(conn, self.tiers, season, start)
        for s in streaks:
            s["text"] = phrasing.streak_line(s, names)

        alt_kind = ALT_TABLES[date.isocalendar()[1] % len(ALT_TABLES)]
        tiers_present = {v["tier"] for v in now.values()}
        sections = []
        for tier in self.tiers:
            in_tier = [r for r in results if r["tier"] == tier]
            if not in_tier and tier not in tiers_present:
                continue
            sections.append({
                "tier": tier, "division_name": TIER_NAMES.get(tier, f"Tier {tier}"),
                "results": in_tier,
                "alt": alternate_table(conn, season, tier, alt_kind, names),
            })

        thin = phrasing.thin_review(self.label) if not results else None
        preview_date = datetime.date.fromisoformat(claims_doc["date"]) if claims_doc else None
        ctx = {
            "date": date, "start": start, "end": end, "label": self.label,
            "result_count": len(results),
            "reckoning": reckoning, "history": history, "sections": sections,
            "streaks": streaks, "alt_kind": alt_kind,
            "alt_title": phrasing.alt_table_title(alt_kind),
            "thin": thin,
            "archive_url": config.archive_url(self.name, date.isoformat()),
            "preview_url": (config.archive_url("preview", preview_date.isoformat())
                            if preview_date else None),
        }
        subject = phrasing.review_subject(ctx)
        html = render.render("review.html", **ctx)
        return EditionOutput(subject=subject, html=html, text=self._text(ctx),
                             images=images, thin=thin, table=now,
                             extra={"covered": sorted(result_key(r) for r in results)})

    @staticmethod
    def _text(ctx: dict) -> str:
        lines = [f"THE WEEKEND REVIEWED - {ctx['label']}, {ctx['start']:%d %b} to {ctx['end']:%d %b}", ""]
        if ctx["thin"]:
            lines.append(ctx["thin"])
        if ctx["reckoning"]:
            lines += ["", "FRIDAY'S PICKS"] + [f"* {r['text']}" for r in ctx["reckoning"]]
        if ctx["history"]:
            lines += ["", "RESULTS THAT MOVED HISTORY"]
            for r in ctx["history"]:
                lines.append(f"* {r['home']} {r['hg']}-{r['ag']} {r['away']}: " + " ".join(r["prose"]))
        for s in ctx["sections"]:
            lines += ["", s["division_name"].upper()]
            for r in s["results"]:
                tag = f"  [{r['tag']}]" if r["tag"] else ""
                lines.append(f"  {r['date']:%a %d}: {r['home']} {r['hg']}-{r['ag']} {r['away']}{tag}")
        if ctx["streaks"]:
            lines += ["", "STREAK WATCH"] + [f"* {s['text']}" for s in ctx["streaks"]]
        return "\n".join(lines)


class ReviewTopEdition(ReviewEdition):
    name = "review-top"
    tiers = (1, 2)
    label = "Premier League and Championship"


class ReviewLowerEdition(ReviewEdition):
    name = "review-lower"
    tiers = (3, 4, 5)
    label = "League One, League Two and the National League"
