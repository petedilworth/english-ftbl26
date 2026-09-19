"""
The Friday preview.

Three speeds in one email, grouped by division: a handful of long-form
matches with a chart and both clubs' records, a second rank with a short
blurb, and every remaining fixture as one line with a tag where the
scorer earned one. Opens with the midweek results when there were any,
and writes the week's claims for the reviews to answer.

The facts layer. It picks and orders; the words are in
templates/email/preview.html and editions/phrasing.py.
"""

import datetime
import json
import logging
import sqlite3
from pathlib import Path

import pandas as pd

import charts
import digest
import entities
import fixtures as fixtures_mod
from editions import config, phrasing, render
from editions.base import Edition, EditionOutput

logger = logging.getLogger(__name__)

# The long-form band is whatever clears the threshold, between these
# bounds. A quiet week runs short rather than promoting a dull fixture;
# a loud one is capped so the email stays readable.
LONG_MIN, LONG_MAX = 2, 6
LONG_THRESHOLD = 12.0
MEDIUM_COUNT = 8

# Monday to Thursday before a Friday send.
MIDWEEK_DAYS = 4

TIER_NAMES = {1: "Premier League", 2: "Championship", 3: "League One",
              4: "League Two", 5: "National League"}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def nearest_rivals(conn: sqlite3.Connection) -> dict[str, tuple[str, float]]:
    """club_id -> (nearest rival club_id, miles), from the catchment model."""
    if not _table_exists(conn, "club_catchment"):
        return {}
    return {
        cid: (rival, miles)
        for cid, rival, miles in conn.execute(
            "SELECT club_id, nearest_rival_id, nearest_rival_miles FROM club_catchment"
            " WHERE nearest_rival_id IS NOT NULL"
        )
    }


def tags_for(fixture: dict, home: dict | None, away: dict | None,
             followed: set[str], rivals: dict[str, tuple[str, float]]) -> list[tuple]:
    """
    Why this fixture is interesting, as neutral codes in priority order.
    The first one is the tag shown in the fixture list; phrasing.tag_label
    turns a code into words. Mirrors the signals storyline_score rewards,
    so a tag is never shown for something the score ignored.
    """
    tags: list[tuple] = []
    if not (home and away):
        return tags
    hid, aid = home["club_id"], away["club_id"]

    if {hid, aid} & followed:
        tags.append(("followed",))
    for a, b in ((hid, aid), (aid, hid)):
        rival = rivals.get(a)
        if rival and rival[0] == b:
            tags.append(("derby", rival[1]))
            break
    if home["position"] and away["position"]:
        if home["position"] <= 3 and away["position"] <= 3:
            tags.append(("top_clash",))
    for ctx in (home, away):
        if ctx["highest_tier"] == 1 and fixture["tier"] >= 3:
            tags.append(("fallen_giant", ctx["name"]))
            break
    gaps = [ctx.get("natural_level_gap") or 0 for ctx in (home, away)]
    below, above = max(gaps), -min(gaps)
    if below >= 1:
        tags.append(("below_level", below))
    if above >= 1:
        tags.append(("above_level", above))
    if home["position"] and away["position"] and abs(home["position"] - away["position"]) <= 3:
        if ("top_clash",) not in tags:
            tags.append(("neighbours",))
    if any(ctx.get("natural_level_kind") == "yo-yo" for ctx in (home, away)):
        tags.append(("yo_yo",))
    for ctx in (home, away):
        last = ctx.get("last_completed")
        status = last[4] if last else None
        if status in ("Promoted", "Play-off Promoted", "Champions", "Relegated"):
            tags.append(("moved", ctx["name"], status))
            break
    return tags


def midweek_results(conn: sqlite3.Connection, date: datetime.date) -> list[dict]:
    """Results from the Monday to Thursday before `date`, tiers 1-5, by division."""
    start = (date - datetime.timedelta(days=MIDWEEK_DAYS)).isoformat()
    rows = conn.execute(
        """
        SELECT tier, match_date, home_name, away_name, fthg, ftag
        FROM matches
        WHERE match_date >= ? AND match_date < ? AND tier <= 5
          AND fthg IS NOT NULL
        ORDER BY tier, match_date, home_name
        """,
        (start, date.isoformat()),
    ).fetchall()
    sections: dict[int, list] = {}
    for tier, d, h, a, hg, ag in rows:
        sections.setdefault(tier, []).append(
            {"date": datetime.date.fromisoformat(d), "home": h, "away": a,
             "hg": int(hg), "ag": int(ag)})
    return [{"tier": t, "division_name": TIER_NAMES.get(t, f"Tier {t}"), "results": r}
            for t, r in sorted(sections.items())]


def table_snapshot(conn: sqlite3.Connection, season: int) -> dict[str, dict]:
    """Every club in tiers 1-5 as the table stands, keyed by club_id."""
    return {
        club_id: {"tier": tier, "position": pos, "points": pts, "played": played}
        for club_id, tier, pos, pts, played in conn.execute(
            "SELECT club_id, tier, position, points, played FROM standings"
            " WHERE season_end_year = ? AND tier <= 5 AND club_id IS NOT NULL",
            (season,))
    }


def snapshot(ctx: dict | None) -> dict | None:
    """The table as it stands, frozen so the reviews can say what moved."""
    if ctx is None:
        return None
    return {
        "club_id": ctx["club_id"], "name": ctx["name"], "tier": ctx["tier"],
        "position": ctx["position"], "points": ctx["points"],
        "played": ctx["played"], "form": ctx["form"],
        "streak_seasons_in_tier": ctx["streak"],
        "natural_level_gap": ctx.get("natural_level_gap"),
    }


def _serial_fixture(f: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime.date) else v)
            for k, v in f.items()}


class PreviewEdition(Edition):
    name = "preview"

    def load_fixtures(self, fixtures_file: Path | None = None) -> list[dict]:
        resolver = entities.build_resolver(self.conn)
        if fixtures_file:
            df = pd.read_csv(fixtures_file, encoding="utf-8-sig",
                             encoding_errors="replace", on_bad_lines="skip")
            return fixtures_mod.parse_fixtures(df, resolver, today=self.date)
        return fixtures_mod.fetch_fixtures(resolver, today=self.date)

    def build(self, fixture_list: list[dict] | None = None,
              fixtures_file: Path | None = None) -> EditionOutput:
        conn, date = self.conn, self.date
        if fixture_list is None:
            fixture_list = self.load_fixtures(fixtures_file)
        followed = digest._followed()
        rivals = nearest_rivals(conn)

        items = []
        for f in fixture_list:
            home = digest.club_context(conn, f["home_id"])
            away = digest.club_context(conn, f["away_id"])
            items.append({
                "fixture": f, "home": home, "away": away,
                "h2h": digest.head_to_head(conn, f["home_id"], f["away_id"]),
                "score": digest.storyline_score(f, home, away, followed),
                "tags": tags_for(f, home, away, followed, rivals),
                "speed": "list",
            })

        ranked = sorted(items, key=lambda i: -i["score"])
        long_form = [i for i in ranked if i["score"] >= LONG_THRESHOLD][:LONG_MAX]
        if len(long_form) < LONG_MIN:
            long_form = ranked[:LONG_MIN]
        medium = [i for i in ranked if i not in long_form][:MEDIUM_COUNT]
        for i in long_form:
            i["speed"] = "long"
        for i in medium:
            i["speed"] = "medium"

        images: list[tuple[Path, str]] = []
        for n, i in enumerate(long_form):
            f, home, away = i["fixture"], i["home"], i["away"]
            i["story"] = phrasing.narrative(f, home, away, i["h2h"])
            cid = f"chart-{n}"
            path = charts.fixture_chart(
                conn, f["home_id"], f["away_id"], f["home_name"], f["away_name"],
                self.chart_dir / f"{cid}.png",
            )
            if path:
                i["cid"] = cid
                images.append((path, cid))
        for i in medium:
            i["blurb"] = phrasing.medium_blurb(i["fixture"], i["home"], i["away"], i["tags"])
        for i in items:
            i["tag_label"] = phrasing.tag_label(i["tags"][0]) if i["tags"] else ""

        sections = []
        for tier in sorted({i["fixture"]["tier"] for i in items}):
            in_tier = [i for i in items if i["fixture"]["tier"] == tier]
            sections.append({
                "tier": tier,
                "division_name": in_tier[0]["fixture"]["division_name"],
                "long": [i for i in in_tier if i["speed"] == "long"],
                "medium": [i for i in in_tier if i["speed"] == "medium"],
                "rest": sorted((i for i in in_tier if i["speed"] == "list"),
                               key=lambda i: (i["fixture"]["date"], i["fixture"]["home_name"])),
            })

        claims = [
            {
                "fixture": _serial_fixture(i["fixture"]),
                "speed": i["speed"],
                "score": round(i["score"], 2),
                "reasons": [list(t) for t in i["tags"]],
                "snapshot": {"home": snapshot(i["home"]), "away": snapshot(i["away"])},
            }
            for i in long_form + medium
        ]

        # Five divisions never go eight days without a league fixture - the
        # National League plays through international breaks - so an empty
        # list is the fixtures file being rewritten under us, or a failed
        # fetch. football-data rewrites fixtures.csv on Friday morning, and
        # one send went out as "nothing to preview" from inside that gap.
        thin = None
        refuse = None
        if not fixture_list:
            thin = phrasing.thin_preview(date)
            refuse = "no fixtures in the file for the next eight days; not sending"

        week_of = min((f["date"] for f in fixture_list), default=date)
        season = fixtures_mod.current_season_end_year(date)
        # The two reviews that answer this preview do not exist yet, but
        # their addresses are fixed by the schedule: Monday and Tuesday.
        monday = date + datetime.timedelta(days=(7 - date.weekday()) % 7 or 7)
        review_links = [
            ("Monday review, tiers 1–2", config.archive_url("review-top", monday.isoformat())),
            ("Tuesday review, tiers 3–5",
             config.archive_url("review-lower", (monday + datetime.timedelta(days=1)).isoformat())),
        ]
        ctx = {
            "date": date, "week_of": week_of,
            "fixture_count": len(fixture_list),
            "division_count": len(sections),
            "sections": sections,
            "midweek": midweek_results(conn, date),
            "thin": thin,
            "archive_url": config.archive_url(self.name, date.isoformat()),
            "review_links": review_links,
        }
        subject = phrasing.preview_subject(ctx)
        html = render.render("preview.html", **ctx)
        text = self._text(ctx)
        return EditionOutput(subject=subject, html=html, text=text,
                             images=images, claims=claims, thin=thin, refuse=refuse,
                             table=table_snapshot(conn, season))

    @staticmethod
    def _text(ctx: dict) -> str:
        lines = [f"THE WEEK AHEAD - week of {ctx['week_of']:%d %B %Y}", ""]
        if ctx["thin"]:
            lines.append(ctx["thin"])
        for s in ctx["sections"]:
            lines += ["", s["division_name"].upper()]
            for i in s["long"]:
                f = i["fixture"]
                lines += [f"* {f['home_name']} v {f['away_name']} ({f['date']:%a %d %b})",
                          f"  {i['story']}"]
            for i in s["medium"]:
                f = i["fixture"]
                lines += [f"* {f['home_name']} v {f['away_name']} ({f['date']:%a %d %b})",
                          f"  {i['blurb']}"]
            for i in s["rest"]:
                f = i["fixture"]
                tag = f"  [{i['tag_label']}]" if i["tag_label"] else ""
                lines.append(f"  {f['date']:%a %d}: {f['home_name']} v {f['away_name']}{tag}")
        return "\n".join(lines)
