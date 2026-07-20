"""
Generate the static website from england.db into site/.

Usage:
    python src/site_build.py [--db-path PATH] [--out PATH] [--no-charts]

Every page is rendered with Jinja2 templates from templates/, styled by
static/. Team narratives are picked up from content/<club_id>.md when
present. Links are relative so the site works at any base path
(GitHub Pages project sites live under /<repo>/).
"""

import argparse
import logging
import shutil
import sqlite3
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_SRC = Path(__file__).parent
sys.path.insert(0, str(_SRC))

PROJECT_ROOT = _SRC.parent

logger = logging.getLogger(__name__)

TIER_SLUGS = {
    1: ("premier-league", "Premier League"),
    2: ("championship", "Championship"),
    3: ("league-one", "League One"),
    4: ("league-two", "League Two"),
    5: ("national-league", "National League"),
}

STATUS_PRESENTATION = {
    "Champions": ("champions", "up", "Champions"),
    "Promoted": ("promoted", "up", "Promoted"),
    "Play-off Promoted": ("play-off-promoted", "up", "Play-offs ↑"),
    "Stayed": ("stayed", "", ""),
    "Play-off Relegated": ("play-off-relegated", "down", "Play-offs ↓"),
    "Relegated": ("relegated", "down", "Relegated"),
}

DEFAULT_COLOR = "#1a5c9a"


def season_slug(year: int) -> str:
    return f"{year - 1}-{year % 100:02d}"


def season_label(year: int) -> str:
    return f"{year - 1}/{year % 100:02d}"


def _row_dict(r) -> dict:
    slug, direction, label = STATUS_PRESENTATION.get(r["status"], ("stayed", "", ""))
    return {
        "club_id": r["club_id"],
        "name": r["club_name"],
        "position": r["position"],
        "played": r["played"],
        "won": r["won"],
        "drawn": r["drawn"],
        "lost": r["lost"],
        "gf": r["gf"],
        "ga": r["ga"],
        "gd": r["gd"],
        "points": r["points"],
        "status_slug": slug,
        "status_dir": direction,
        "status_label": label,
    }


class SiteBuilder:
    def __init__(self, db_path: Path, out_dir: Path, charts_enabled: bool = True):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.out = out_dir
        self.charts_enabled = charts_enabled
        self.env = Environment(
            loader=FileSystemLoader(PROJECT_ROOT / "templates"), autoescape=True
        )
        self.colors = self._load_colors()
        self.seasons = [
            r[0] for r in self.conn.execute(
                "SELECT DISTINCT season_end_year FROM standings ORDER BY season_end_year"
            )
        ]
        if not self.seasons:
            raise SystemExit("standings table is empty — run the pipeline first")

    def _load_colors(self) -> dict[str, str]:
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(club_master)")}
        if "color_primary" not in cols:
            return {}
        colors = {}
        for club_id, primary, secondary in self.conn.execute(
            "SELECT club_id, color_primary, color_secondary FROM club_master"
            " WHERE color_primary IS NOT NULL"
        ):
            # White/near-white shirts are invisible as accents; use the trim color
            if primary and primary.upper() in ("#FFFFFF", "#FFF", "#FFFEFE"):
                colors[club_id] = secondary or DEFAULT_COLOR
            else:
                colors[club_id] = primary
        return colors

    def color(self, club_id: str | None) -> str:
        return self.colors.get(club_id, DEFAULT_COLOR)

    def render(self, template: str, out_path: Path, depth: int, **ctx) -> None:
        ctx["root"] = "/".join([".."] * depth) if depth else "."
        html = self.env.get_template(template).render(**ctx)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")

    # ── Queries ────────────────────────────────────────────────────────────

    def season_divisions(self, year: int) -> list[dict]:
        divisions = []
        for tier in sorted({
            r[0] for r in self.conn.execute(
                "SELECT DISTINCT tier FROM standings WHERE season_end_year = ?", (year,)
            )
        }):
            rows = self.conn.execute(
                """
                SELECT * FROM standings
                WHERE season_end_year = ? AND tier = ? ORDER BY position
                """,
                (year, tier),
            ).fetchall()
            divisions.append({
                "tier": tier,
                "name": rows[0]["division_name"] if rows else TIER_SLUGS[tier][1],
                "rows": [_row_dict(r) for r in rows],
            })
        return divisions

    # ── Pages ──────────────────────────────────────────────────────────────

    def build_home(self) -> None:
        current = self.seasons[-1]
        team_count = self.conn.execute("SELECT COUNT(*) FROM club_master").fetchone()[0]
        self.render(
            "home.html", self.out / "index.html", 0,
            title="Home",
            current_label=season_label(current),
            divisions=self.season_divisions(current),
            season_count=len(self.seasons),
            team_count=team_count,
        )

    def build_seasons(self) -> None:
        entries = []
        for year in reversed(self.seasons):
            champ = self.conn.execute(
                """
                SELECT club_name FROM standings
                WHERE season_end_year = ? AND tier = 1 AND position = 1
                """,
                (year,),
            ).fetchone()
            entries.append({
                "slug": season_slug(year),
                "label": season_label(year),
                "champions": f"Champions: {champ[0]}" if champ else "",
            })
        self.render(
            "seasons_index.html", self.out / "seasons" / "index.html", 1,
            title="Seasons", seasons=entries,
        )

        for i, year in enumerate(self.seasons):
            prev_year = self.seasons[i - 1] if i > 0 else None
            next_year = self.seasons[i + 1] if i < len(self.seasons) - 1 else None
            self.render(
                "season.html",
                self.out / "season" / season_slug(year) / "index.html", 2,
                title=season_label(year),
                season_label=season_label(year),
                divisions=self.season_divisions(year),
                prev_slug=season_slug(prev_year) if prev_year else None,
                prev_label=season_label(prev_year) if prev_year else None,
                next_slug=season_slug(next_year) if next_year else None,
                next_label=season_label(next_year) if next_year else None,
            )

    def build_divisions(self) -> None:
        index_entries = []
        for tier, (slug, name) in TIER_SLUGS.items():
            season_years = [
                r[0] for r in self.conn.execute(
                    "SELECT DISTINCT season_end_year FROM standings WHERE tier = ?"
                    " ORDER BY season_end_year DESC",
                    (tier,),
                )
            ]
            if not season_years:
                continue
            index_entries.append({
                "slug": slug, "name": name, "tier": tier,
                "season_count": len(season_years),
            })
            seasons = []
            for year in season_years:
                rows = self.conn.execute(
                    """
                    SELECT * FROM standings
                    WHERE season_end_year = ? AND tier = ? ORDER BY position
                    """,
                    (year, tier),
                ).fetchall()
                seasons.append({
                    "label": season_label(year),
                    "division_name": rows[0]["division_name"],
                    "rows": [_row_dict(r) for r in rows],
                })
            self.render(
                "division.html", self.out / "division" / slug / "index.html", 2,
                title=name, division_title=name, tier=tier, seasons=seasons,
            )

        self.render(
            "division_index.html", self.out / "division" / "index.html", 1,
            title="Divisions", divisions=index_entries,
        )

    def _team_stats_cards(self, t: sqlite3.Row) -> list[dict]:
        cards = [
            {"value": f"Tier {t['current_tier']}", "label": "Current level"},
            {"value": t["current_tier_streak"], "label": "Seasons at this level"},
            {"value": f"{t['highest_tier']}–{t['lowest_tier']}", "label": "Tier range"},
            {"value": t["total_promotions"], "label": "Promotions"},
            {"value": t["total_relegations"], "label": "Relegations"},
            {"value": t["yo_yo_score"], "label": "Yo-yo score"},
        ]
        if t["seasons_in_tier1"]:
            cards.insert(2, {
                "value": t["seasons_in_tier1"],
                "label": f"Top-flight seasons (last {t['last_tier1_season']})",
            })
        return cards

    def _tagline(self, t: sqlite3.Row) -> str:
        span = f"{season_label(t['first_season_in_db'])}–{season_label(t['last_season_in_db'])}"
        if t["highest_tier"] == 1 and t["current_tier"] >= 3:
            return f"Fallen giant · {span}"
        if t["yo_yo_score"] and t["yo_yo_score"] >= 0.25:
            return f"Yo-yo club · {span}"
        return span

    def build_teams(self) -> None:
        import markdown as md

        trajectories = self.conn.execute(
            """
            SELECT * FROM club_trajectory ORDER BY canonical_name
            """
        ).fetchall()

        content_dir = PROJECT_ROOT / "content"

        teams_meta = []
        for t in trajectories:
            club_id = t["club_id"]
            seasons = []
            for r in self.conn.execute(
                "SELECT * FROM standings WHERE club_id = ? ORDER BY season_end_year DESC",
                (club_id,),
            ):
                d = _row_dict(r)
                d["season_slug"] = season_slug(r["season_end_year"])
                d["season_label"] = season_label(r["season_end_year"])
                d["division_name"] = r["division_name"]
                seasons.append(d)

            narrative_html = None
            md_file = content_dir / f"{club_id}.md"
            if md_file.exists():
                from markupsafe import Markup
                narrative_html = Markup(md.markdown(md_file.read_text(encoding="utf-8")))

            out_dir = self.out / "team" / club_id
            has_chart = False
            if self.charts_enabled:
                import charts
                chart_path = charts.fixture_chart(
                    self.conn, club_id, None, t["canonical_name"], "",
                    out_dir / "chart.png",
                )
                has_chart = chart_path is not None

            self.render(
                "team.html", out_dir / "index.html", 2,
                title=t["canonical_name"],
                name=t["canonical_name"],
                color=self.color(club_id),
                tagline=self._tagline(t),
                stats=self._team_stats_cards(t),
                has_chart=has_chart,
                first_season=season_label(t["first_season_in_db"]),
                last_season=season_label(t["last_season_in_db"]),
                narrative_html=narrative_html,
                seasons=seasons,
            )

            teams_meta.append({
                "club_id": club_id,
                "name": t["canonical_name"],
                "tier": t["current_tier"],
                "tier_label": TIER_SLUGS.get(t["current_tier"], (None, f"Tier {t['current_tier']}"))[1],
                "color": self.color(club_id),
                "search_key": "".join(c if c.isalnum() else " " for c in t["canonical_name"].lower()).strip(),
            })

        by_tier = []
        for tier, (_slug, label) in TIER_SLUGS.items():
            group = [t for t in teams_meta if t["tier"] == tier]
            if group:
                by_tier.append({"label": label, "teams": group})
        others = [t for t in teams_meta if t["tier"] not in TIER_SLUGS]
        if others:
            by_tier.append({"label": "Below Tier 5 / historic", "teams": others})

        az = {}
        for t in teams_meta:
            az.setdefault(t["name"][0].upper(), []).append(t)

        self.render(
            "teams_index.html", self.out / "teams" / "index.html", 1,
            title="Teams",
            teams=teams_meta,
            by_tier=by_tier,
            az=sorted(az.items()),
            letters=sorted(az.keys()),
        )

    def build_chart(self) -> None:
        import json

        import charts as charts_mod

        tier_floors = {}
        max_pos = 0
        for year in self.seasons:
            counts = self.conn.execute(
                """
                SELECT tier, COUNT(*) FROM standings
                WHERE season_end_year = ? GROUP BY tier ORDER BY tier
                """,
                (year,),
            ).fetchall()
            floors, running = [], 0
            for _tier, n in counts:
                running += n
                floors.append(running)
            max_pos = max(max_pos, running)
            tier_floors[str(year)] = floors[:-1]  # boundaries between tiers

        clubs = []
        for t in self.conn.execute(
            "SELECT club_id, canonical_name FROM club_trajectory ORDER BY canonical_name"
        ):
            series = charts_mod.overall_positions(self.conn, t["club_id"])
            if series:
                clubs.append({
                    "id": t["club_id"],
                    "name": t["canonical_name"],
                    "color": self.color(t["club_id"]),
                    "series": series,
                })

        payload = {
            "years": self.seasons,
            "maxPos": max_pos,
            "tierFloors": tier_floors,
            "clubs": clubs,
        }
        out_dir = self.out / "chart"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "chart-data.js").write_text(
            "window.CHART_DATA = " + json.dumps(payload) + ";", encoding="utf-8"
        )
        self.render(
            "chart.html", out_dir / "index.html", 1,
            title="Trajectory chart",
            first_label=season_label(self.seasons[0]),
            last_label=season_label(self.seasons[-1]),
        )

    def build_matrix(self) -> None:
        tiers = []
        for tier, (_slug, name) in TIER_SLUGS.items():
            columns = []
            for year in self.seasons:
                rows = self.conn.execute(
                    """
                    SELECT club_id, club_name, status FROM standings
                    WHERE season_end_year = ? AND tier = ? ORDER BY position
                    """,
                    (year, tier),
                ).fetchall()
                if not rows:
                    continue
                columns.append({
                    "label": season_label(year),
                    "clubs": [
                        {
                            "club_id": r["club_id"],
                            "name": r["club_name"],
                            "status_slug": STATUS_PRESENTATION.get(
                                r["status"], ("stayed", "", "")
                            )[0],
                        }
                        for r in rows
                    ],
                })
            if columns:
                tiers.append({"name": name, "columns": columns})

        self.render(
            "matrix.html", self.out / "matrix" / "index.html", 1,
            title="The Matrix", tiers=tiers,
        )

    # ── Insights ───────────────────────────────────────────────────────────

    @staticmethod
    def _cell(text, club_id=None, num=False):
        return {"text": text, "club_id": club_id, "num": num}

    def build_insights(self) -> None:
        entries = [
            {"slug": "yo-yo", "name": "Yo-yo clubs", "sub": "The volatility league"},
            {"slug": "fallen-giants", "name": "Fallen giants & risers",
             "sub": "Long falls and great climbs"},
            {"slug": "records", "name": "Records & extremes",
             "sub": "The best and worst seasons"},
            {"slug": "timeline", "name": "Timeline", "sub": "Notable events since 1993"},
        ]
        self.render(
            "insights_index.html", self.out / "insights" / "index.html", 1,
            title="Insights", entries=entries,
        )
        self._insight_yo_yo()
        self._insight_fallen_giants()
        self._insight_records()
        self._insight_timeline()

    def _insight_yo_yo(self) -> None:
        rows = self.conn.execute(
            """
            SELECT * FROM (
                SELECT t.club_id, t.canonical_name, t.yo_yo_score,
                       t.total_promotions, t.total_relegations,
                       (SELECT COUNT(*) FROM standings s
                        WHERE s.club_id = t.club_id) AS n
                FROM club_trajectory t
            ) WHERE n >= 5
            ORDER BY yo_yo_score DESC, n DESC LIMIT 25
            """
        ).fetchall()
        self.render(
            "insight_table.html", self.out / "insights" / "yo-yo" / "index.html", 2,
            title="Yo-yo clubs",
            heading="Yo-yo clubs",
            intro="Promotions plus relegations per recorded season — the clubs that can't sit still. Minimum five seasons in the database.",
            sections=[{
                "columns": ["#", "Club", "Yo-yo score", "Promotions", "Relegations", "Seasons"],
                "rows": [
                    [self._cell(i + 1, num=True),
                     self._cell(r["canonical_name"], r["club_id"]),
                     self._cell(r["yo_yo_score"], num=True),
                     self._cell(r["total_promotions"], num=True),
                     self._cell(r["total_relegations"], num=True),
                     self._cell(r["n"], num=True)]
                    for i, r in enumerate(rows)
                ],
            }],
        )

    def _insight_fallen_giants(self) -> None:
        fallen = self.conn.execute(
            """
            SELECT club_id, canonical_name, seasons_in_tier1, last_tier1_season,
                   current_tier
            FROM club_trajectory
            WHERE highest_tier = 1 AND current_tier >= 3
            ORDER BY current_tier DESC, last_tier1_season
            """
        ).fetchall()
        risers = self.conn.execute(
            """
            SELECT * FROM (
                SELECT t.club_id, t.canonical_name, t.current_tier,
                       t.first_season_in_db,
                       (SELECT s.tier FROM standings s WHERE s.club_id = t.club_id
                        ORDER BY s.season_end_year LIMIT 1) AS first_tier
                FROM club_trajectory t
            ) WHERE first_tier >= 4 AND current_tier <= 2
            ORDER BY current_tier, first_tier DESC
            """
        ).fetchall()
        self.render(
            "insight_table.html",
            self.out / "insights" / "fallen-giants" / "index.html", 2,
            title="Fallen giants & risers",
            heading="Fallen giants & risers",
            intro="Clubs a long way from where they once were — in both directions.",
            sections=[
                {
                    "heading": "Fallen giants",
                    "note": "Former top-flight clubs now in Tier 3 or below.",
                    "columns": ["Club", "Top-flight seasons", "Last in Tier 1", "Now"],
                    "rows": [
                        [self._cell(r["canonical_name"], r["club_id"]),
                         self._cell(r["seasons_in_tier1"], num=True),
                         self._cell(season_label(r["last_tier1_season"])),
                         self._cell(f"Tier {r['current_tier']}")]
                        for r in fallen
                    ],
                },
                {
                    "heading": "The risers",
                    "note": "Clubs that entered the database in Tier 4 or 5 and now play in the top two divisions.",
                    "columns": ["Club", "Started", "Now"],
                    "rows": [
                        [self._cell(r["canonical_name"], r["club_id"]),
                         self._cell(f"Tier {r['first_tier']} in {season_label(r['first_season_in_db'])}"),
                         self._cell(f"Tier {r['current_tier']}")]
                        for r in risers
                    ],
                },
            ],
        )

    def _insight_records(self) -> None:
        def _standings_section(heading, note, order, limit=10, where="s.played >= 30"):
            rows = self.conn.execute(
                f"""
                SELECT s.club_id, s.club_name, s.season_end_year, s.division_name,
                       s.position, s.points, s.gd
                FROM standings s WHERE {where}
                ORDER BY {order} LIMIT {limit}
                """
            ).fetchall()
            return {
                "heading": heading,
                "note": note,
                "columns": ["Club", "Season", "Division", "Pos", "Pts", "GD"],
                "rows": [
                    [self._cell(r["club_name"], r["club_id"]),
                     self._cell(season_label(r["season_end_year"])),
                     self._cell(r["division_name"]),
                     self._cell(r["position"], num=True),
                     self._cell(r["points"], num=True),
                     self._cell(r["gd"], num=True)]
                    for r in rows
                ],
            }

        streaks = self.conn.execute(
            """
            SELECT club_id, canonical_name, current_tier, current_tier_streak
            FROM club_trajectory ORDER BY current_tier_streak DESC LIMIT 10
            """
        ).fetchall()

        self.render(
            "insight_table.html", self.out / "insights" / "records" / "index.html", 2,
            title="Records & extremes",
            heading="Records & extremes",
            intro="The outer edges of thirty years of league tables.",
            sections=[
                _standings_section("Most points in a season", "Full seasons only.",
                                   "s.points DESC, s.gd DESC"),
                _standings_section("Fewest points in a season", "The campaigns to forget.",
                                   "s.points ASC, s.gd ASC"),
                _standings_section("Best goal difference", "", "s.gd DESC, s.points DESC"),
                _standings_section("Worst goal difference", "", "s.gd ASC, s.points ASC"),
                {
                    "heading": "Longest unbroken runs at current level",
                    "note": "Consecutive seasons at the club's current tier.",
                    "columns": ["Club", "Level", "Seasons"],
                    "rows": [
                        [self._cell(r["canonical_name"], r["club_id"]),
                         self._cell(f"Tier {r['current_tier']}"),
                         self._cell(r["current_tier_streak"], num=True)]
                        for r in streaks
                    ],
                },
            ],
        )

    def _insight_timeline(self) -> None:
        events = [
            {"year": 1995, "title": "The Premier League shrinks",
             "text": "Four clubs relegated in 1994/95 as the top flight cuts from 22 to 20; the Third Division expands to 24 to rebalance the pyramid."},
            {"year": 1996, "title": "Stevenage denied, Torquay reprieved",
             "text": "Conference champions Stevenage Borough are refused promotion on ground grading, so nobody goes down from the Football League."},
            {"year": 2002, "title": "Two-up two-down with the Conference",
             "text": "From 2002/03 two clubs are exchanged between the Football League and the Conference each season — and the Conference gains play-offs."},
            {"year": 2003, "title": "Wimbledon leave SW19",
             "text": "Wimbledon FC relocate 60 miles to Milton Keynes mid-crisis; within a year they are rebranded MK Dons. Fan-founded AFC Wimbledon start seven tiers down and climb back."},
            {"year": 2010, "title": "Chester City expelled mid-season",
             "text": "Chester City are wound up in March 2010 and their Conference record is expunged, leaving the division a club short."},
            {"year": 2011, "title": "Rushden & Diamonds fold",
             "text": "Expelled from the Conference and liquidated within weeks."},
            {"year": 2019, "title": "Bury expelled from the Football League",
             "text": "The first Football League expulsion since 1992. League One plays the season with 23 clubs and only three go down."},
            {"year": 2020, "title": "COVID stops the game",
             "text": "Leagues One and Two and the National League end early on points-per-game; Macclesfield Town are relegated by points deduction, then wound up entirely months later."},
            {"year": 2021, "title": "The season with no relegation",
             "text": "With the leagues below voided, nobody is relegated from the 23-club National League."},
            {"year": 2022, "title": "Wrexham go global",
             "text": "Hollywood ownership turns a National League ever-present into the world's most-watched lower-league club — promotion follows in 2023."},
        ]
        self.render(
            "timeline.html", self.out / "insights" / "timeline" / "index.html", 2,
            title="Timeline", events=events,
        )

    # ── Groundhop map ─────────────────────────────────────────────────────

    def build_map(self) -> None:
        import json

        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(club_master)")}
        if "latitude" not in cols:
            logger.warning("No stadium coordinates in club_master — skipping map")
            return

        clubs = []
        for r in self.conn.execute(
            """
            SELECT cm.club_id, cm.canonical_name, cm.stadium_name,
                   cm.latitude, cm.longitude, cm.current_tier,
                   t.highest_tier, t.yo_yo_score,
                   t.first_season_in_db, t.last_season_in_db
            FROM club_master cm
            JOIN club_trajectory t ON t.club_id = cm.club_id
            WHERE cm.latitude IS NOT NULL
            """
        ):
            tiers = {
                str(row[0]): row[1]
                for row in self.conn.execute(
                    "SELECT season_end_year, tier FROM standings WHERE club_id = ?",
                    (r["club_id"],),
                )
            }
            n_seasons = len(tiers)
            clubs.append({
                "id": r["club_id"],
                "name": r["canonical_name"],
                "stadium": r["stadium_name"] or "",
                "lat": r["latitude"],
                "lon": r["longitude"],
                "color": self.color(r["club_id"]),
                "tier": r["current_tier"],
                "defunct": r["current_tier"] == 0,
                "fallen": r["highest_tier"] == 1 and (r["current_tier"] or 9) >= 3,
                "yoyo": (r["yo_yo_score"] or 0) >= 0.25,
                "everpresent": n_seasons == len(self.seasons),
                "tiers": tiers,
            })

        out_dir = self.out / "map"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "map-data.js").write_text(
            "window.MAP_DATA = " + json.dumps({"years": self.seasons, "clubs": clubs}) + ";",
            encoding="utf-8",
        )
        self.render(
            "map.html", out_dir / "index.html", 1,
            title="Groundhop Map",
            first_year=self.seasons[0],
            last_year=self.seasons[-1],
            last_label=season_label(self.seasons[-1]),
        )

    # ── Digest archive ────────────────────────────────────────────────────

    def build_digest_archive(self) -> None:
        archive_src = PROJECT_ROOT / "content" / "digests"
        entries = []
        if archive_src.exists():
            for item in sorted(archive_src.iterdir(), reverse=True):
                if item.is_dir() and (item / "index.html").exists():
                    shutil.copytree(item, self.out / "digest" / item.name)
                    entries.append({"slug": item.name, "name": item.name,
                                    "sub": "Weekly preview"})
        self.render(
            "insights_index.html", self.out / "digest" / "index.html", 1,
            title="Digest archive",
            entries=[
                {"slug": e["slug"], "name": e["name"], "sub": e["sub"]}
                for e in entries
            ] or [{"slug": ".", "name": "No digests archived yet",
                   "sub": "They appear here after each Monday email"}],
        )

    def build(self) -> None:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        shutil.copytree(PROJECT_ROOT / "static", self.out / "static")
        (self.out / ".nojekyll").write_text("")

        self.build_home()
        self.build_seasons()
        self.build_divisions()
        self.build_teams()
        self.build_chart()
        self.build_matrix()
        self.build_insights()
        self.build_map()
        self.build_digest_archive()

        page_count = sum(1 for _ in self.out.rglob("index.html"))
        logger.info("Site built: %d pages in %s", page_count, self.out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the static site")
    parser.add_argument("--db-path", type=Path,
                        default=PROJECT_ROOT / "data" / "db" / "england.db")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "site")
    parser.add_argument("--no-charts", action="store_true",
                        help="skip per-team chart PNGs (faster dev builds)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    if not args.db_path.exists():
        logger.error("Database not found at %s — run the pipeline first", args.db_path)
        return 1

    SiteBuilder(args.db_path, args.out, charts_enabled=not args.no_charts).build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
