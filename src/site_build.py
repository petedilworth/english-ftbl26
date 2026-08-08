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

import content  # noqa: E402  (needs _SRC on the path first)

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


OWNERSHIP_LABELS = {
    "fan_trust": "Fan / supporters' trust",
    "family": "Family / local dynasty",
    "benefactor": "Benefactor-funded",
    "consortium": "Consortium",
    "foreign_investment": "Foreign investment",
    "multi_club": "Multi-club group",
    "celebrity_media": "Celebrity / media ownership",
    "plc": "Public limited company",
}

STADIUM_OWNERSHIP_LABELS = {
    "club": "Owned by the club",
    "council": "Council-owned",
    "third_party": "Owned by a third party",
    "disputed": "Ownership disputed",
}

ORIGIN_LABELS = {
    "works": "Works team",
    "church": "Church team",
    "pub": "Pub team",
    "school": "School / old boys",
    "youth": "Youth / street team",
    "civic": "Civic founding",
    "phoenix": "Phoenix club",
    "other": "Other",
}


def _facts_rows(facts: dict) -> list[dict]:
    """
    Turn front-matter into an ordered list of {label, value} rows for the
    club facts panel. Only facts actually present are returned, so a
    thinly-researched club shows a short panel rather than a row of blanks.
    """
    rows = []

    def add(label, value):
        if value not in (None, "", [], {}):
            rows.append({"label": label, "value": str(value)})

    add("Nickname", facts.get("nickname"))

    founded = facts.get("founded")
    if founded:
        origin = ORIGIN_LABELS.get(facts.get("origin_type"))
        add("Founded", f"{founded} · {origin}" if origin else founded)
    elif facts.get("origin_type"):
        add("Origin", ORIGIN_LABELS.get(facts["origin_type"]))
    add("Formed as", facts.get("origin_note"))

    owner = facts.get("owner")
    if owner:
        since = facts.get("owner_since")
        add("Owner", f"{owner} (since {since})" if since else owner)
    add("Ownership model", OWNERSHIP_LABELS.get(facts.get("ownership_model")))
    add("Multi-club group", facts.get("multi_club_group"))

    stadium = facts.get("stadium")
    if stadium:
        opened = facts.get("stadium_opened")
        add("Stadium", f"{stadium} (opened {opened})" if opened else stadium)
    add("Ground ownership", STADIUM_OWNERSHIP_LABELS.get(facts.get("stadium_ownership")))
    if facts.get("capacity"):
        add("Capacity", f"{int(facts['capacity']):,}")
    if facts.get("pitch_type") == "artificial_3g":
        add("Pitch", "Artificial 3G")

    for grounds in (facts.get("previous_grounds") or []):
        if isinstance(grounds, dict) and grounds.get("name"):
            years = grounds.get("years")
            add("Former ground", f"{grounds['name']} ({years})" if years else grounds["name"])

    for spell in (facts.get("exile") or []):
        if isinstance(spell, dict) and spell.get("venue"):
            bits = [spell["venue"]]
            if spell.get("seasons"):
                bits.append(str(spell["seasons"]))
            if spell.get("distance_miles"):
                bits.append(f"~{spell['distance_miles']} miles away")
            add("Played home games at", " · ".join(bits))

    for event in (facts.get("administration") or []):
        if isinstance(event, dict) and event.get("year"):
            pts = event.get("points_deducted")
            add("Administration", f"{event['year']}"
                + (f" · −{pts} points" if pts else ""))

    for event in (facts.get("points_deductions") or []):
        if isinstance(event, dict) and event.get("points"):
            season = event.get("season_end_year")
            label = f"−{event['points']} points"
            if season:
                label += f" in {season_label(int(season))}"
            if event.get("reason"):
                label += f" · {event['reason']}"
            add("Points deduction", label)

    for denial in (facts.get("ground_grading_denial") or []):
        if isinstance(denial, dict):
            season = denial.get("season_end_year")
            note = denial.get("note") or "Promotion denied on ground grading"
            add("Ground grading", f"{season_label(int(season))} · {note}" if season else note)

    if facts.get("phoenix_of"):
        folded = facts.get("predecessor_folded")
        add("Successor to", f"{facts['phoenix_of']}"
            + (f" (folded {folded})" if folded else ""))

    for label, key in (("Featured on The drop", "drops"), ("Featured on The rise", "rises")):
        for item in (facts.get(key) or []):
            if isinstance(item, dict) and item.get("note"):
                season = item.get("season")
                value = f"{season_label(int(season))} · {item['note']}" if season else item["note"]
                add(label, value)

    return rows


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
        # {club_id: [theme_slug, ...]} - filled by build_teams, consumed by
        # build_themes, so themes always reflect what the club pages rendered.
        # club_facts carries the front-matter alongside, which is what the
        # theme pages derive their event dots and narrative from.
        self.club_themes: dict[str, list[str]] = {}
        self.club_facts: dict[str, dict] = {}
        # The database file is committed, so a checkout can carry a
        # club_trajectory predating the natural-level columns. Cache the
        # column set once so the build degrades instead of raising.
        self.trajectory_cols = {
            r[1] for r in self.conn.execute("PRAGMA table_info(club_trajectory)")
        }
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

    def _natural_level(self, t: sqlite3.Row) -> dict | None:
        """
        The club's natural level, ready for the team page, or None when
        there isn't enough record to say. A thin club gets a shorter page
        rather than a panel full of dashes - same rule as _facts_rows.
        """
        if "natural_level_tier" not in self.trajectory_cols:
            return None
        if t["natural_level_tier"] is None:
            return None

        import json

        import level as level_mod

        dist = json.loads(t["tier_distribution"] or "{}")
        total = sum(dist.values()) or 1
        segments = []
        for key in ["1", "2", "3", "4", "5", "outside"]:
            n = dist.get(key, 0)
            if not n:
                continue
            outside = key == "outside"
            segments.append({
                "key": key,
                "name": (level_mod.bucket_name(level_mod.OUTSIDE, t["coverage_note"])
                         if outside else level_mod.TIER_NAMES[int(key)]),
                "seasons": n,
                "pct": round(100 * n / total, 2),
                "outside": outside,
            })

        recorded, seasons = t["natural_level_recorded"], t["natural_level_seasons"]
        window = (f"{seasons} seasons, {recorded} of them inside the top five tiers"
                  if recorded < seasons else f"{seasons} recorded seasons")

        trend_line = None
        if t["natural_level_trend"] and t["recent_level_tier"]:
            recent = level_mod.bucket_name(t["recent_level_tier"], t["coverage_note"])
            trend_line = {
                "rising": f"Rising — the last five seasons average out at {recent}.",
                "falling": f"Falling — the last five seasons average out at {recent}.",
                "level": "Holding steady against the previous decade.",
            }.get(t["natural_level_trend"])

        gap, gap_line = t["natural_level_gap"], None
        if gap is not None and gap != 0:
            n = abs(gap)
            direction = "below" if gap > 0 else "above"
            gap_line = f"Currently {n} division{'s' if n > 1 else ''} {direction} that level."

        return {
            "label": t["natural_level_label"],
            "window_note": window,
            "segments": segments,
            "trend_line": trend_line,
            "gap_line": gap_line,
        }

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
        if ("natural_level_tier" in self.trajectory_cols
                and t["natural_level_tier"] is not None):
            import level as level_mod
            # Just the division name - the full label would overflow the card
            cards.insert(0, {
                "value": level_mod.bucket_name(t["natural_level_tier"], t["coverage_note"]),
                "label": "Natural level",
            })
        return cards

    def _tagline(self, t: sqlite3.Row) -> str:
        span = f"{season_label(t['first_season_in_db'])}–{season_label(t['last_season_in_db'])}"
        if ("natural_level_label" in self.trajectory_cols
                and t["natural_level_label"] and t["natural_level_kind"] != "insufficient"):
            return f"{t['natural_level_label']} · {span}"
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

            club_content = content.load_club(content_dir / f"{club_id}.md")
            story_sections = []
            facts_rows = []
            club_themes = []
            extra_html = None
            nickname = None
            if club_content:
                from markupsafe import Markup

                for key, heading in content.SECTIONS.items():
                    body = club_content["sections"].get(key)
                    if body:
                        story_sections.append({
                            "heading": heading,
                            "html": Markup(md.markdown(body)),
                        })
                if club_content["extra"]:
                    extra_html = Markup(md.markdown(club_content["extra"]))
                facts_rows = _facts_rows(club_content["facts"])
                club_themes = [
                    {"slug": s, "label": content.THEMES.get(s, s.replace("-", " ").title())}
                    for s in club_content["themes"]
                ]
                self.club_themes[club_id] = club_content["themes"]
                self.club_facts[club_id] = club_content["facts"]
                nickname = club_content["facts"].get("nickname")

            out_dir = self.out / "team" / club_id
            has_chart = False
            if self.charts_enabled:
                import charts
                chart_path = charts.fixture_chart(
                    self.conn, club_id, None, t["canonical_name"], "",
                    out_dir / "chart.png",
                    show_tier_lines=True,
                    show_events=True,
                    color_by_tier=True,
                )
                has_chart = chart_path is not None

            self.render(
                "team.html", out_dir / "index.html", 2,
                title=t["canonical_name"],
                name=t["canonical_name"],
                nickname=nickname,
                color=self.color(club_id),
                tagline=self._tagline(t),
                natural_level=self._natural_level(t),
                stats=self._team_stats_cards(t),
                has_chart=has_chart,
                first_season=season_label(t["first_season_in_db"]),
                last_season=season_label(t["last_season_in_db"]),
                story_sections=story_sections,
                extra_html=extra_html,
                facts_rows=facts_rows,
                club_themes=club_themes,
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

        floors_by_year, max_pos = charts_mod.tier_floors(self.conn)
        tier_floors_json = {str(year): floors for year, floors in floors_by_year.items()}

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
                    "series": series,  # [year, overall_pos, event|null] triples
                })

        payload = {
            "years": self.seasons,
            "maxPos": max_pos,
            "tierFloors": tier_floors_json,
            "clubs": clubs,
            # The global chart starts empty - 160 lines at once says nothing.
            "preselect": [],
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

    def build_themes(self) -> None:
        """
        Cross-club theme pages, from the facts each club's story declares.
        Runs after build_teams, which populates self.club_themes.
        """
        names = {
            r["club_id"]: r["canonical_name"]
            for r in self.conn.execute(
                "SELECT club_id, canonical_name FROM club_trajectory"
            )
        }

        import json

        import charts as charts_mod
        import markdown as md
        from markupsafe import Markup

        floors_by_year, max_pos = charts_mod.tier_floors(self.conn)
        tier_floors_json = {str(year): floors for year, floors in floors_by_year.items()}
        themes_dir = PROJECT_ROOT / "content" / "themes"

        by_theme: dict[str, list[str]] = {}
        for club_id, themes in self.club_themes.items():
            for slug in themes:
                by_theme.setdefault(slug, []).append(club_id)

        entries = []
        for slug in sorted(by_theme):
            label = content.THEMES.get(slug, slug.replace("-", " ").capitalize())
            club_ids = sorted(by_theme[slug], key=lambda c: names.get(c, c))

            clubs, chart_clubs = [], []
            for club_id in club_ids:
                facts = self.club_facts.get(club_id, {})
                events = content.theme_events(slug, facts)
                series = charts_mod.overall_positions(self.conn, club_id)
                plotted = {year for year, _pos, _ev in series}

                clubs.append({
                    "club_id": club_id,
                    "name": names.get(club_id, club_id),
                    "color": self.color(club_id),
                    "narrative": content.theme_narrative(slug, facts),
                    # Events that predate the standings can't sit on the chart,
                    # so they're flagged for the narrative to carry instead.
                    "events": [{
                        "label": e["label"],
                        "season": season_label(e["season_end_year"]),
                        "text": e["text"],
                        "on_chart": e["season_end_year"] in plotted,
                    } for e in events],
                })
                if series:
                    chart_clubs.append({
                        "id": club_id,
                        "name": names.get(club_id, club_id),
                        "color": self.color(club_id),
                        "series": series,
                        "events": events,
                    })

            out_dir = self.out / "themes" / slug
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "chart-data.js").write_text(
                "window.CHART_DATA = " + json.dumps({
                    "years": self.seasons,
                    "maxPos": max_pos,
                    "tierFloors": tier_floors_json,
                    "clubs": chart_clubs,
                    # Every club in the theme is drawn on arrival; the picker
                    # is there to take them away, not to start from nothing.
                    "preselect": [c["id"] for c in chart_clubs],
                }) + ";",
                encoding="utf-8",
            )

            intro = content.load_theme(themes_dir / f"{slug}.md")
            entries.append({
                "slug": slug,
                "name": label,
                "sub": f"{len(clubs)} club{'s' if len(clubs) != 1 else ''}",
            })
            self.render(
                "theme.html", out_dir / "index.html", 2,
                title=label, heading=label, clubs=clubs,
                intro_html=Markup(md.markdown(intro)) if intro else None,
                has_chart=bool(chart_clubs),
            )

        self.render(
            "themes_index.html", self.out / "themes" / "index.html", 1,
            title="Themes", entries=entries,
        )

    def build_matrix(self) -> None:
        # One shared season axis (most recent first) so every division's row
        # scrolls in lockstep and a given column always means the same year.
        season_years = list(reversed(self.seasons))
        season_columns = [season_label(y) for y in season_years]

        rows = []
        for tier, (_slug, name) in TIER_SLUGS.items():
            cells = []
            has_data = False
            for year in season_years:
                clubs = self.conn.execute(
                    """
                    SELECT club_id, club_name, status FROM standings
                    WHERE season_end_year = ? AND tier = ? ORDER BY position
                    """,
                    (year, tier),
                ).fetchall()
                if clubs:
                    has_data = True
                cells.append([
                    {
                        "club_id": r["club_id"],
                        "name": r["club_name"],
                        "color": self.color(r["club_id"]),
                        "status_slug": STATUS_PRESENTATION.get(
                            r["status"], ("stayed", "", "")
                        )[0],
                    }
                    for r in clubs
                ])
            if has_data:
                rows.append({"name": name, "cells": cells})

        self.render(
            "matrix.html", self.out / "matrix" / "index.html", 1,
            title="The Matrix", season_columns=season_columns, rows=rows,
            main_class="wide",
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
        if "natural_level_gap" in self.trajectory_cols:
            entries.insert(1, {
                "slug": "natural-level",
                "name": "Above and below their level",
                "sub": "Clubs out of step with their own history",
            })
        if self._capacity_points():
            entries.append({
                "slug": "capacity",
                "name": "Stadium size vs. league position",
                "sub": "Does a bigger ground mean a higher division?",
            })
        boom_bust_events = self._boom_bust_events()
        if boom_bust_events:
            entries.append({
                "slug": "boom-and-bust",
                "name": "Boom and bust",
                "sub": "Why the same clubs keep falling into financial trouble",
            })
        movement_matches = self._movement_matches()
        import movement as movement_mod
        if any(movement_matches.get(k) for k in (
            movement_mod.RELEGATION_BACK_TO_BACK, movement_mod.RELEGATION_THREE_PLUS,
            movement_mod.RELEGATION_HELD, movement_mod.RELEGATION_SANDWICH,
        )):
            entries.append({
                "slug": "the-drop",
                "name": "The drop",
                "sub": "Clubs that fell fast — and whether they came back",
            })
        if any(movement_matches.get(k) for k in (
            movement_mod.PROMOTION_BACK_TO_BACK, movement_mod.PROMOTION_THREE_PLUS,
            movement_mod.PROMOTION_PAUSED,
        )):
            entries.append({
                "slug": "the-rise",
                "name": "The rise",
                "sub": "Clubs that climbed fast — and whether they held on",
            })
        self.render(
            "insights_index.html", self.out / "insights" / "index.html", 1,
            title="Insights", entries=entries,
        )
        self._insight_yo_yo()
        self._insight_natural_level()
        self._insight_fallen_giants()
        self._insight_records()
        self._insight_timeline()
        self._insight_capacity()
        self._insight_boom_and_bust(boom_bust_events)
        self._insight_the_drop(movement_matches)
        self._insight_the_rise(movement_matches)

    def _boom_bust_events(self) -> list[dict]:
        """
        Every administration and points-deduction event across the clubs
        with a story file, flattened into one chronological list. Reuses
        content.theme_events() rather than re-parsing the facts, since that
        function already handles the calendar-year vs season-end-year
        normalisation that caused a real bug earlier (Coventry's 2013
        administration and 2013/14 points deduction landing on different
        seasons if handled naively).
        """
        names = dict(self.conn.execute(
            "SELECT club_id, canonical_name FROM club_trajectory"
        ))
        events = []
        for club_id, facts in self.club_facts.items():
            for slug in ("administration", "points-deductions"):
                for e in content.theme_events(slug, facts):
                    events.append({
                        "club_id": club_id,
                        "name": names.get(club_id, club_id),
                        "kind": slug,
                        **e,
                    })
        events.sort(key=lambda e: e["season_end_year"])
        return events

    def _insight_boom_and_bust(self, events: list[dict]) -> None:
        if not events:
            return

        import markdown as md
        from markupsafe import Markup

        source = PROJECT_ROOT / "content" / "insights" / "boom-and-bust.md"
        prose = content.load_theme(source)
        # load_theme() only returns prose; the case-study club_ids live in
        # this file's own front-matter, so parse it directly rather than
        # extending load_theme() for a single caller's sake.
        page_facts, _body = content.parse_front_matter(
            source.read_text(encoding="utf-8") if source.exists() else ""
        )

        def case_study(club_id: str | None) -> dict | None:
            if not club_id:
                return None
            row = self.conn.execute(
                """
                SELECT canonical_name, natural_level_label, yo_yo_score,
                       total_promotions, total_relegations
                FROM club_trajectory WHERE club_id = ?
                """,
                (club_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "club_id": club_id,
                "name": row["canonical_name"],
                "color": self.color(club_id),
                "natural_level_label": row["natural_level_label"],
                "yo_yo_score": row["yo_yo_score"],
                "total_promotions": row["total_promotions"],
                "total_relegations": row["total_relegations"],
            }

        clubs_affected = {e["club_id"] for e in events}
        # Counted from points_deductions specifically, not administration's
        # own points_deducted - some clubs (e.g. Aldershot Town) record the
        # same single penalty in both places, so summing both would double
        # it. This slightly undercounts a club whose administration-linked
        # penalty has no separate points_deductions entry (Coventry City's
        # first ten points, distinct from their later second deduction),
        # but never overcounts, which matters more for a headline figure.
        total_points_lost = sum(
            int(pd.get("points") or 0)
            for facts in self.club_facts.values()
            for pd in (facts.get("points_deductions") or [])
            if isinstance(pd, dict)
        )

        stats = [
            {"value": len(clubs_affected), "label": "Clubs affected"},
            {"value": len(events), "label": "Recorded events"},
            {"value": total_points_lost, "label": "Points deductions on record"},
            {"value": f"{events[0]['season_end_year'] - 1}–{events[-1]['season_end_year']}",
             "label": "Span of the record"},
        ]

        rows = [
            [self._cell(season_label(e["season_end_year"])),
             self._cell(e["name"], e["club_id"]),
             self._cell("Administration" if e["kind"] == "administration" else "Points deduction"),
             self._cell(e["text"])]
            for e in reversed(events)  # most recent first, like the rest of the site
        ]

        self.render(
            "insight_table.html", self.out / "insights" / "boom-and-bust" / "index.html", 2,
            title="Boom and bust",
            heading="Boom and bust",
            intro=(
                "Why promotion pays and relegation can break a club — and every "
                "recorded administration or points deduction since 1993/94."
            ),
            intro_html=Markup(md.markdown(prose)) if prose else None,
            stats=stats,
            case_study_promoted=case_study(page_facts.get("case_study_promoted")),
            case_study_relegated=case_study(page_facts.get("case_study_relegated")),
            sections=[{
                "columns": ["Season", "Club", "Event", "What happened"],
                "rows": rows,
            }],
        )

    def _movement_matches(self) -> dict[str, list[dict]]:
        """
        {pattern_key: [match, ...]} across every club - see src/movement.py
        for the pattern rules. Computed once and shared between the
        insights-index tile guard and both pages that render from it, same
        as _boom_bust_events()/_insight_boom_and_bust().
        """
        import movement

        names = dict(self.conn.execute(
            "SELECT club_id, canonical_name FROM club_trajectory"
        ))
        histories = movement.load_status_histories(self.conn)

        by_pattern: dict[str, list[dict]] = {}
        for club_id, history in histories.items():
            for m in movement.detect_patterns(history):
                by_pattern.setdefault(m["pattern"], []).append({
                    "club_id": club_id,
                    "name": names.get(club_id, club_id),
                    **m,
                })
        return by_pattern

    # Display labels for the pattern keys movement.py returns. Kept here
    # rather than in movement.py so the module stays presentation-free.
    _PATTERN_LABELS = {
        "relegation_back_to_back": "Back-to-back",
        "relegation_three_plus": "Three in a row",
        "relegation_held": "Held, then down again",
        "relegation_sandwich": "Straight back down",
        "promotion_back_to_back": "Back-to-back",
        "promotion_three_plus": "Three in a row",
        "promotion_paused": "Paused, then up again",
    }

    def _ribbon(self, tiers: dict[int, int], marked: set[int]) -> list[dict]:
        """
        One cell per season across the whole record, coloured by the tier
        the club was in. A season with no standings row is hatched rather
        than coloured - it means "outside Tiers 1-5", which is not the same
        as knowing which division they were in.
        """
        cells = []
        for year in self.seasons:
            tier = tiers.get(year)
            cells.append({
                "cls": f"t{tier}" if tier else "out",
                "marked": year in marked,
                "title": f"{season_label(year)}: " + (
                    TIER_SLUGS[tier][1] if tier in TIER_SLUGS else "outside Tiers 1-5"
                ),
            })
        return cells

    def _movement_page(
        self, by_pattern, *, slug, title, intro, patterns, outcome_of,
        groups, featured_heading, event_column, stats_fn, feature_key,
    ) -> None:
        """
        Shared renderer for The drop and The rise. The two pages differ only
        in which patterns they collect, how an outcome is computed, and how
        the outcome groups are worded - everything else (ribbons, featured
        cards, tier key, sorting) is identical, so it lives here once.
        """
        import movement
        import level as level_mod
        import markdown as md
        from markupsafe import Markup

        entries = [e for key in patterns for e in by_pattern.get(key, [])]
        if not entries:
            return

        tiers_by_club = level_mod.load_histories(self.conn)
        latest = self.seasons[-1]

        records = []
        for e in entries:
            tiers = tiers_by_club.get(e["club_id"], {})
            before, floor, peak = movement.sequence_bounds(tiers, e["seasons"])
            now = tiers.get(latest)
            records.append({
                "club_id": e["club_id"],
                "name": e["name"],
                "color": self.color(e["club_id"]),
                "ribbon": self._ribbon(tiers, set(e["seasons"])),
                "pattern_label": self._PATTERN_LABELS.get(e["pattern"], e["pattern"]),
                "path": "{} — {} to {}".format(
                    " → ".join(season_label(y) for y in e["seasons"]),
                    level_mod.TIER_NAMES.get(e["tiers"][0], "?"),
                    level_mod.TIER_NAMES.get(
                        floor if outcome_of is movement.fall_outcome else peak, "?"
                    ),
                ),
                # A run that ends in the most recent season has no season
                # after it yet, so no outcome can honestly be claimed.
                "outcome": outcome_of(before, floor, now,
                                      e["seasons"][-1] < latest)
                           if outcome_of is movement.fall_outcome
                           else outcome_of(peak, now, e["seasons"][-1] < latest),
                "seasons": e["seasons"],
            })

        records.sort(key=lambda r: r["seasons"][-1], reverse=True)

        sections = []
        for key, heading, note in groups:
            rows = [r for r in records if r["outcome"] == key]
            if rows:
                sections.append({"heading": heading, "note": note, "rows": rows})

        source = PROJECT_ROOT / "content" / "insights" / f"{slug}.md"
        prose = content.load_theme(source)

        # Featured cards are authored on the club's own page (facts[feature_key]
        # = "drops" or "rises"), not curated here - same direction of
        # dependency as every other cross-club page on the site. `season`
        # picks which pattern a note belongs to, since several clubs match
        # more than one (Luton Town have both a 2007-09 slide out of the
        # League and a 2024-25 one). A season that doesn't match a real
        # pattern is skipped rather than shown, so a typo degrades silently
        # instead of breaking the build.
        labels = {key: heading for key, heading, _note in groups}
        featured = []
        for club_id, facts in self.club_facts.items():
            for item in facts.get(feature_key) or []:
                if not isinstance(item, dict) or not item.get("note"):
                    continue
                match = next(
                    (r for r in records
                     if r["club_id"] == club_id and r["seasons"][-1] == item.get("season")),
                    None,
                )
                if match:
                    featured.append({
                        **match,
                        "note": item["note"],
                        "outcome_class": match["outcome"],
                        "outcome_label": labels.get(match["outcome"], match["outcome"]),
                    })
                else:
                    logger.warning(
                        "%s: %s entry for season %s doesn't match any detected "
                        "pattern - skipped",
                        club_id, feature_key, item.get("season"),
                    )
        featured.sort(key=lambda f: f["seasons"][-1], reverse=True)

        tier_key = [
            {"cls": f"t{t}", "label": name}
            for t, name in sorted(level_mod.TIER_NAMES.items())
        ] + [{"cls": "out", "label": "outside Tiers 1-5"}]

        self.render(
            "insight_movement.html", self.out / "insights" / slug / "index.html", 2,
            title=title, heading=title, intro=intro,
            intro_html=Markup(md.markdown(prose)) if prose else None,
            stats=stats_fn(records),
            featured=featured,
            featured_heading=featured_heading,
            sections=sections,
            span_label=f"{season_label(self.seasons[0])}–{season_label(latest)}",
            event_column=event_column,
            tier_key=tier_key,
        )

    def _insight_the_drop(self, by_pattern: dict[str, list[dict]]) -> None:
        import movement

        def stats(records):
            back = sum(1 for r in records if r["outcome"] == movement.FALL_RECOVERED)
            return [
                {"value": len(records), "label": "Falls on record"},
                {"value": len({r["club_id"] for r in records}), "label": "Clubs"},
                {"value": back, "label": "Fully reversed"},
                {"value": sum(1 for r in records
                              if r["outcome"] in (movement.FALL_STUCK, movement.OUTSIDE)),
                 "label": "Still down there"},
            ]

        self._movement_page(
            by_pattern,
            slug="the-drop",
            title="The drop",
            intro="Clubs that fell through the divisions in a tight cluster — "
                  "and whether they ever came back.",
            patterns=(movement.RELEGATION_BACK_TO_BACK, movement.RELEGATION_THREE_PLUS,
                      movement.RELEGATION_HELD, movement.RELEGATION_SANDWICH),
            outcome_of=movement.fall_outcome,
            groups=[
                (movement.FALL_RECOVERED, "All the way back",
                 "Back at the division they fell from, or higher."),
                (movement.FALL_CLIMBING, "Still climbing",
                 "Above the level they fell to, but not yet back where they started."),
                (movement.FALL_STUCK, "Still down there",
                 "Still at the division the fall took them to."),
                (movement.FALL_WORSE, "Fell further",
                 "Lower now than the division the fall itself took them to."),
                (movement.OUTSIDE, "Out of the pyramid",
                 "No longer in Tiers 1-5 at all."),
                (movement.UNFOLDING, "Still unfolding",
                 "The fall only just finished — the season that would show "
                 "a recovery has not been played yet."),
            ],
            featured_heading="The ones who came back",
            event_column="The fall",
            stats_fn=stats,
            feature_key="drops",
        )

    def _insight_the_rise(self, by_pattern: dict[str, list[dict]]) -> None:
        import movement

        def stats(records):
            return [
                {"value": len(records), "label": "Climbs on record"},
                {"value": len({r["club_id"] for r in records}), "label": "Clubs"},
                {"value": sum(1 for r in records if r["outcome"] == movement.RISE_HELD),
                 "label": "Held the new level"},
                {"value": sum(1 for r in records
                              if r["outcome"] in (movement.RISE_SLIPPED,
                                                  movement.RISE_FELL_BACK,
                                                  movement.OUTSIDE)),
                 "label": "Slipped back"},
            ]

        self._movement_page(
            by_pattern,
            slug="the-rise",
            title="The rise",
            intro="Clubs that climbed through the divisions in a tight cluster — "
                  "and whether they held on to it.",
            patterns=(movement.PROMOTION_BACK_TO_BACK, movement.PROMOTION_THREE_PLUS,
                      movement.PROMOTION_PAUSED),
            outcome_of=movement.rise_outcome,
            groups=[
                (movement.RISE_HELD, "Held the new level",
                 "Still at the division the climb took them to, or higher."),
                (movement.RISE_SLIPPED, "Slipped one division",
                 "One division below the level they reached."),
                (movement.RISE_FELL_BACK, "Fell back further",
                 "More than one division below the level they reached."),
                (movement.OUTSIDE, "Out of the pyramid",
                 "No longer in Tiers 1-5 at all."),
                (movement.UNFOLDING, "Still unfolding",
                 "The climb only just finished — the season at the new "
                 "level has not been played yet."),
            ],
            featured_heading="The ones who kept going",
            event_column="The climb",
            stats_fn=stats,
            feature_key="rises",
        )

    def _capacity_points(self) -> list[dict]:
        """
        Clubs with a stadium capacity on record (from their story file),
        each mapped to their overall pyramid position in the current
        season. Only ~12 of 162 clubs have a story file yet, so this is
        small by design rather than by bug - it grows as more are written.

        Restricted to the current season specifically (not "each club's own
        most recent season") because the chart draws this season's tier
        boundary lines - a club plotted against an older season's position
        would sit at the right x for a pyramid shape that no longer existed,
        misaligned against boundaries that describe a different season. A
        club currently outside Tiers 1-5 (e.g. relegated to Tier 6) simply
        has no row this season and is excluded, same as everywhere else
        "current" standing is used on the site.
        """
        candidates = {
            cid: facts["capacity"]
            for cid, facts in self.club_facts.items()
            if isinstance(facts.get("capacity"), (int, float))
        }
        if not candidates:
            return []

        placeholders = ",".join("?" * len(candidates))
        rows = self.conn.execute(
            f"""
            SELECT s.club_id, s.tier, s.position,
                   s.position + (
                       SELECT COUNT(*) FROM standings s2
                       WHERE s2.season_end_year = s.season_end_year
                         AND s2.tier < s.tier
                   ) AS overall_pos
            FROM standings s
            WHERE s.club_id IN ({placeholders})
              AND s.season_end_year = (SELECT MAX(season_end_year) FROM standings)
            """,
            list(candidates),
        ).fetchall()

        names = dict(self.conn.execute("SELECT club_id, canonical_name FROM club_trajectory"))
        points = []
        for club_id, tier, position, overall_pos in rows:
            points.append({
                "club_id": club_id,
                "name": names.get(club_id, club_id),
                "color": self.color(club_id),
                "tier": tier,
                "division_name": TIER_SLUGS.get(tier, (None, f"Tier {tier}"))[1],
                "position": position,
                "overall_pos": overall_pos,
                "capacity": int(candidates[club_id]),
            })
        return sorted(points, key=lambda p: p["overall_pos"])

    def _insight_capacity(self) -> None:
        points = self._capacity_points()
        if not points:
            return

        import charts as charts_mod

        floors_by_year, max_pos = charts_mod.tier_floors(self.conn)
        latest = max(floors_by_year)
        boundaries = floors_by_year[latest]

        caps = [p["capacity"] for p in points]
        cap_min, cap_max = min(caps), max(caps)
        # A little headroom so the extreme points aren't drawn on the frame.
        # Clamped at 0 - a stadium can't hold a negative number of people,
        # and with few points the raw min can be small enough that padding
        # below it would otherwise cross zero.
        pad = max(1, round((cap_max - cap_min) * 0.08))
        cap_min, cap_max = max(0, cap_min - pad), cap_max + pad

        W, H = 760, 380
        PAD = {"top": 16, "right": 20, "bottom": 36, "left": 64}
        span_x = max(1, max_pos - 1)
        span_y = max(1, cap_max - cap_min)

        def x(pos):
            return PAD["left"] + (pos - 1) / span_x * (W - PAD["left"] - PAD["right"])

        def y(cap):
            return PAD["top"] + (1 - (cap - cap_min) / span_y) * (H - PAD["top"] - PAD["bottom"])

        for p in points:
            p["cx"] = round(x(p["overall_pos"]), 1)
            p["cy"] = round(y(p["capacity"]), 1)

        boundary_lines = [round(x(b + 0.5), 1) for b in boundaries]
        total_clubs = self.conn.execute("SELECT COUNT(*) FROM club_master").fetchone()[0]

        self.render(
            "insight_scatter.html", self.out / "insights" / "capacity" / "index.html", 2,
            title="Stadium size vs. league position",
            heading="Stadium size vs. league position",
            intro=(
                f"Ground capacity from the club stories written so far "
                f"({len(points)} of {total_clubs} clubs) against each club's overall "
                f"position across all five tiers this season. Dashed lines mark the "
                f"boundary between divisions. This fills in as more stories are written."
            ),
            points=points,
            boundary_lines=boundary_lines,
            width=W, height=H,
            plot_top=PAD["top"], plot_bottom=H - PAD["bottom"],
            axis_y=H - PAD["bottom"] + 16,
            x_min_label=1, x_max_label=max_pos,
            cap_min_label=f"{cap_min:,}", cap_max_label=f"{cap_max:,}",
            legend=[{"tier": t, "name": name, "key": t}
                    for t, (_slug, name) in TIER_SLUGS.items()],
        )

    def _insight_natural_level(self) -> None:
        """
        Clubs whose current division is out of step with the level their
        own record says they belong at.
        """
        if "natural_level_gap" not in self.trajectory_cols:
            return

        import level as level_mod

        def table(where: str, order: str) -> list[list]:
            rows = self.conn.execute(
                f"""
                SELECT club_id, canonical_name, natural_level_label,
                       natural_level_tier, current_tier, natural_level_gap,
                       coverage_note
                FROM club_trajectory
                WHERE natural_level_gap IS NOT NULL AND {where}
                ORDER BY {order}, canonical_name LIMIT 25
                """
            ).fetchall()
            return [
                [self._cell(i + 1, num=True),
                 self._cell(r["canonical_name"], r["club_id"]),
                 self._cell(r["natural_level_label"]),
                 self._cell(level_mod.bucket_name(r["current_tier"], r["coverage_note"])),
                 self._cell(abs(r["natural_level_gap"]), num=True)]
                for i, r in enumerate(rows)
            ]

        columns = ["#", "Club", "Natural level", "Now", "Divisions"]
        self.render(
            "insight_table.html",
            self.out / "insights" / "natural-level" / "index.html", 2,
            title="Above and below their level",
            heading="Above and below their level",
            intro=(
                "A club's natural level is where the balance of its record since "
                "1993/94 puts it. These are the clubs furthest from it right now. "
                "Climbing above your level is usually a moment; falling below it is "
                "usually structural, and harder to reverse."
            ),
            sections=[
                {"heading": "Playing above their level",
                 "note": "Climbing, and usually enjoying a moment rather than a new normal.",
                 "columns": columns, "rows": table("natural_level_gap < 0", "natural_level_gap ASC")},
                {"heading": "Playing below their level",
                 "note": "Falling below your level does financial damage that compounds, which is why it is harder to reverse.",
                 "columns": columns, "rows": table("natural_level_gap > 0", "natural_level_gap DESC")},
            ],
        )

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
        # Tier names travel with the payload so the map legend and the rest of
        # the site name divisions from the same place (TIER_SLUGS).
        tier_names = {str(tier): label for tier, (_slug, label) in TIER_SLUGS.items()}
        (out_dir / "map-data.js").write_text(
            "window.MAP_DATA = "
            + json.dumps({"years": self.seasons, "clubs": clubs, "tierNames": tier_names})
            + ";",
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
        self.build_themes()   # after build_teams: consumes self.club_themes
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
