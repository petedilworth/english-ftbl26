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

    def build_insights_stub(self) -> None:
        # Placeholder until Phase C lands the four insight pages.
        entries = [
            {"slug": "yo-yo", "name": "Yo-yo clubs", "sub": "Coming soon"},
            {"slug": "fallen-giants", "name": "Fallen giants & risers", "sub": "Coming soon"},
            {"slug": "records", "name": "Records & extremes", "sub": "Coming soon"},
            {"slug": "timeline", "name": "Timeline of notable events", "sub": "Coming soon"},
        ]
        self.render(
            "division_index.html", self.out / "insights" / "index.html", 1,
            title="Insights",
            divisions=[
                {"slug": e["slug"], "name": e["name"], "tier": "—", "season_count": 0}
                for e in entries
            ],
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
        self.build_insights_stub()

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
