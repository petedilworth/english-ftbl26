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
import math
import shutil
import sqlite3
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_SRC = Path(__file__).parent
sys.path.insert(0, str(_SRC))

import content  # noqa: E402  (needs _SRC on the path first)
import finances  # noqa: E402  (disclosure states for the club finances table)

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
    # A season still being played has no outcome to tag yet.
    "In progress": ("in-progress", "", ""),
}

IN_PROGRESS_STATUS = "In progress"

DEFAULT_COLOR = "#1a5c9a"


def _ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th - including the 11th/12th/13th exceptions."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _parse_flags(raw: str | None) -> list[str]:
    """flags is a free-form JSON array; a malformed one shouldn't stop a build."""
    if not raw:
        return []
    import json

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _search_key(name: str) -> str:
    """
    Fold a club name to the alphanumeric-and-spaces form both search boxes
    match against, so the home page and the teams index can never disagree
    about what "Brighton & Hove Albion" is called.
    """
    return "".join(c if c.isalnum() else " " for c in name.lower()).strip()


def _fmt_money(value: float) -> str:
    """Money at football scale: £661.0m, £8.9m, £450k. Sign kept for losses."""
    sign = "−" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000:
        return f"{sign}£{v / 1_000_000:.1f}m"
    if v >= 1_000:
        return f"{sign}£{v / 1_000:.0f}k"
    return f"{sign}£{v:,.0f}"


# The scatter insight plots one metric against overall league position.
# Each entry says where the value comes from, how the y-axis should behave
# and how to write the number down.
#
# Scales are not cosmetic. Revenue and wages span roughly £1.5m in the
# National League to £700m+ at Manchester United - close to three orders of
# magnitude - so a linear axis flattens everything below the Premier League
# onto the baseline; those are logarithmic. Profit and net debt both go
# negative (a loss, or net cash), which log cannot represent at all, so they
# use a signed linear axis with a zero line. Capacity keeps its original
# linear behaviour clamped at zero.
METRICS = {
    "capacity": {
        "label": "Stadium capacity",
        "heading": "Stadium size vs. league position",
        "sub": "Does a bigger ground mean a higher division?",
        "base": "insights/capacity",
        "source": "facts",
        "field": "capacity",
        "scale": "linear",
        "format": lambda v: f"{int(v):,}",
        "format_kind": "count",
        "noun": "capacity",
    },
    "revenue": {
        "label": "Revenue",
        "heading": "Revenue vs. league position",
        "sub": "What clubs earn, against where they finish",
        "base": "insights/finances/revenue",
        "source": "finances",
        "field": "turnover",
        "scale": "log",
        "format": _fmt_money,
        "format_kind": "money",
        "noun": "revenue",
    },
    "wages": {
        "label": "Wage bill",
        "heading": "Wage bill vs. league position",
        "sub": "Staff costs from the accounts, against where they finish",
        "base": "insights/finances/wages",
        "source": "finances",
        "field": "staff_costs",
        "scale": "log",
        "format": _fmt_money,
        "format_kind": "money",
        "noun": "wage bill",
    },
    "wage-ratio": {
        "label": "Wages ÷ revenue",
        "heading": "Wage bill as a share of revenue vs. league position",
        "sub": "The overreach metric, comparable across every tier",
        "base": "insights/finances/wage-ratio",
        "source": "finances",
        "field": "wage_ratio",
        "scale": "linear",
        "format": lambda v: f"{v:.0f}%",
        "format_kind": "percent",
        "noun": "wages as a share of revenue",
        # UEFA treats 70% as the outer edge of sustainable.
        "benchmark": {"value": 70.0, "label": "70% — UEFA benchmark"},
    },
    "profit": {
        "label": "Profit / loss",
        "heading": "Profit and loss vs. league position",
        "sub": "Who makes money, and who does not",
        "base": "insights/finances/profit",
        "source": "finances",
        "field": "profit_before_tax",
        "scale": "signed",
        "format": _fmt_money,
        "format_kind": "money",
        "noun": "profit before tax",
    },
    "net-debt": {
        "label": "Net debt",
        "heading": "Net debt vs. league position",
        "sub": "What clubs owe — negative means net cash",
        "base": "insights/finances/net-debt",
        "source": "finances",
        "field": "net_debt",
        "scale": "signed",
        "format": _fmt_money,
        "format_kind": "money",
        "noun": "net debt",
    },
}

# Capacity keeps the URL it has always had; the insights index links it.
LEGACY_METRIC = "capacity"


# Why a figure on a club page can't be read at face value. Only the flags
# that change how a reader should interpret the number appear here -
# "press_reported" is deliberately absent because it applies to every row,
# so it belongs in the one standing provenance line under the table rather
# than repeated as a per-club caveat.
FLAG_LABELS = {
    "non_12_month_period":
        "One period isn't 12 months long, so it isn't like-for-like with the others.",
    "figure_disputed":
        "Outlets reported materially different values for at least one figure.",
    "profit_label_uncertain":
        "Sources didn't agree whether a profit figure is before or after tax.",
    "staff_costs_basis_uncertain":
        "A wage figure is reported without confirming whether it includes "
        "amortisation of transfer fees.",
    "staff_costs_disputed_omitted":
        "A wage bill is left blank because sources couldn't be reconciled.",
    "profit_figure_omitted":
        "A profit figure is left blank because sources disagreed on which "
        "measure applies.",
    "profit_includes_one_off_related_party_gain":
        "A result is flattered by a one-off sale within the owner's group.",
    "profit_includes_one_off_exceptional_gain":
        "A result is flattered by a one-off item outside normal trading.",
    "loss_includes_one_off_exceptional_charge":
        "A result is worsened by a one-off item outside normal trading.",
    "turnover_may_include_transfer_fees":
        "A turnover figure may include transfer income rather than trading "
        "revenue alone.",
    "disclosed_via_statement_not_filed_accounts":
        "Figures come from the club's own statement; the filing itself omitted "
        "the profit and loss account.",
}

# Non-disclosure is a state, not a gap - so the table says what the club
# did rather than showing an empty row.
DISCLOSURE_NOTES = {
    finances.DISCLOSURE_SMALL_COMPANY:
        "Filed under the small-company regime — no profit and loss account disclosed.",
    finances.DISCLOSURE_NOT_FILED:
        "Accounts overdue and not filed.",
    finances.DISCLOSURE_DISSOLVED:
        "Entity dissolved.",
}


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


def _facts_rows(facts: dict, club_names: dict[str, str] | None = None) -> list[dict]:
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

    for rivalry in (facts.get("rivalries") or []):
        if isinstance(rivalry, dict) and rivalry.get("opponent"):
            opponent = (club_names or {}).get(rivalry["opponent"], rivalry["opponent"])
            bits = [f"vs {opponent}" + (f" ({rivalry['name']})" if rivalry.get("name") else "")]
            if rivalry.get("note"):
                bits.append(rivalry["note"])
            add("Rivalry", " · ".join(bits))

    return rows


def _row_dict(r) -> dict:
    slug, direction, label = STATUS_PRESENTATION.get(r["status"], ("stayed", "", ""))
    keys = r.keys()
    # points is the final total, deduction already taken off, as every other
    # published table shows it. The deduction is carried alongside so a
    # reader can see why w*3 + d doesn't add up to the Pts column.
    deducted = r["points_deducted"] if "points_deducted" in keys else 0
    return {
        "points_deducted": deducted or 0,
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
        # Same reasoning for club_finances, which a checkout may predate
        # entirely. Resolved lazily on first use, then cached.
        self._finances_table: bool | None = None
        # Division ranks for every club-season, built once on first use -
        # build_teams walks every club, so a query per club would be wasteful.
        self._finance_ranks_cache: dict | None = None
        # build_insights, _insight_scatter and the home hooks all ask the
        # same (metric, season) questions, and each answer walks the season.
        self._metric_points_cache: dict = {}
        self.standings_cols = {
            r[1] for r in self.conn.execute("PRAGMA table_info(standings)")
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
                "coverage_note": self._coverage_note(year, tier, len(rows)),
                # The column only appears in tables that have one, otherwise
                # every table on the site gains an empty column.
                "has_deductions": any(
                    _row_dict(r)["points_deducted"] for r in rows
                ),
            })
        return divisions

    def _coverage_note(self, year: int, tier: int, n_teams: int) -> str:
        """
        Say so, on the table itself, when the table isn't the real one.

        A reader looking at 2002/03 League One sees clubs on 30 games in a
        46-game season and no explanation. The points and positions shown are
        what the fixtures we hold add up to, not what settled the division -
        which is exactly the sort of gap this site prints rather than hides.
        """
        if "data_complete" not in self.standings_cols:
            return ""
        row = self.conn.execute(
            "SELECT COALESCE(data_complete, 1) FROM standings"
            " WHERE season_end_year = ? AND tier = ? LIMIT 1",
            (year, tier),
        ).fetchone()
        if not row or row[0]:
            return ""
        found = self.conn.execute(
            "SELECT COUNT(*) FROM matches WHERE season_end_year = ? AND tier = ?",
            (year, tier),
        ).fetchone()[0]
        expected = n_teams * (n_teams - 1)
        if not found or not expected or found >= expected:
            return ""
        return (
            f"Only {found} of this division's {expected} fixtures are in the "
            f"source data, so these totals and positions are not the final "
            f"table. They are excluded from records elsewhere on the site."
        )

    # ── Pages ──────────────────────────────────────────────────────────────

    def build_home(self) -> None:
        current = self.seasons[-1]
        divisions = self.season_divisions(current)
        # Same reachable-things rule as the scale bar: club_master carries a
        # club with no trajectory row and so no team page.
        team_count = self.conn.execute(
            "SELECT COUNT(*) FROM club_trajectory"
        ).fetchone()[0]
        self.render(
            "home.html", self.out / "index.html", 0,
            title="Home",
            current_label=season_label(current),
            divisions=divisions,
            season_note=self._season_progress_note(divisions),
            scale=self._home_scale(),
            hooks=self._home_hooks(),
            search_clubs=self._home_search_clubs(),
            has_map=self._has_grounds(),
            season_count=len(self.seasons),
            team_count=team_count,
        )

    # ── Home page ──────────────────────────────────────────────────────────

    def _has_grounds(self) -> bool:
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(club_master)")}
        return "latitude" in cols and bool(self.conn.execute(
            "SELECT 1 FROM club_master WHERE latitude IS NOT NULL LIMIT 1"
        ).fetchone())

    def _home_scale(self) -> list[dict]:
        """
        What the site actually holds, for the bar under the title.

        Every figure is counted rather than written down - a hardcoded "162
        clubs" drifts silently the first time the Monday pipeline adds one -
        and a figure that comes back zero drops its card instead of
        advertising an empty shelf. A fresh clone with no story files should
        say nothing about story files.
        """
        content_dir = PROJECT_ROOT / "content"
        stories = sum(
            1 for r in self.conn.execute("SELECT club_id FROM club_trajectory")
            if (content_dir / f"{r[0]}.md").exists()
        )
        accounts = 0
        if self._has_finances():
            accounts = self.conn.execute(
                "SELECT COUNT(*) FROM club_finances"
            ).fetchone()[0]
        grounds = 0
        if self._has_grounds():
            # Joined the same way build_map joins, so the bar counts the pins
            # the map actually draws rather than every row with a coordinate.
            grounds = self.conn.execute(
                """
                SELECT COUNT(*) FROM club_master cm
                JOIN club_trajectory t ON t.club_id = cm.club_id
                WHERE cm.latitude IS NOT NULL
                """
            ).fetchone()[0]

        cards = [
            # club_trajectory, not club_master: a club without a trajectory
            # row gets no team page, and the teams index counts the same way.
            # Every figure here should point at something reachable.
            (self.conn.execute(
                "SELECT COUNT(*) FROM club_trajectory").fetchone()[0], "clubs"),
            (len(self.seasons), "seasons"),
            (stories, "written histories"),
            (accounts, "club-season accounts"),
            (grounds, "grounds mapped"),
        ]
        return [
            {"value": f"{n:,}", "label": label} for n, label in cards if n
        ]

    def _home_search_clubs(self) -> list[dict]:
        """
        The club list behind the home search box. build_home runs before
        build_teams, so this comes straight from the trajectory table rather
        than from the teams_meta that page assembles - same source, same
        _search_key, no ordering dependency between the two builders.
        """
        return [
            {
                "club_id": r["club_id"],
                "name": r["canonical_name"],
                "search_key": _search_key(r["canonical_name"]),
            }
            for r in self.conn.execute(
                "SELECT club_id, canonical_name FROM club_trajectory"
                " ORDER BY canonical_name"
            )
        ]

    def _season_progress_note(self, divisions: list[dict]) -> str:
        """
        Name an early season for what it is. The newest season enters the
        database as soon as its first results land, so for weeks the home
        table can be one division deep with every club on P1 - which reads
        as a broken page unless the page says otherwise.
        """
        started, total = len(divisions), len(TIER_SLUGS)
        if not started or started >= total:
            return ""
        played = max(
            (row["played"] or 0)
            for division in divisions for row in division["rows"]
        ) if any(d["rows"] for d in divisions) else 0
        opening = (
            f"{started} of {total} divisions have kicked off"
            if started > 1 else
            f"Only {divisions[0]['name']} has kicked off"
        )
        if played and played <= 3:
            return f"{opening}, {played} game{'s' if played != 1 else ''} in."
        return f"{opening}."

    def _home_hooks(self, limit: int = 5) -> list[dict]:
        """
        The "show me something interesting" door: a few findings with real
        numbers in them, each linking to the page that explains it.

        Computed from the database at build time, never written down. The
        pipeline refreshes the data every Monday, so a hardcoded figure
        would go stale silently - and unsourced numbers are against the
        grain of a site that prints an honest "14th of 15" rather than a
        flattering "14th of 24".

        Recipes run in a fixed order, strongest first, and each returns None
        when its data isn't there, so the section shrinks rather than
        breaks. Deliberately not randomised: two builds of the same database
        should be byte-identical, or nobody can diff a deploy.
        """
        recipes = (
            self._hook_fell_out_of_the_league,
            self._hook_wage_ratio,
            self._hook_biggest_loss,
            self._hook_outspender,
            self._hook_points_relegated,
            self._hook_longest_stay,
        )
        hooks: list[dict] = []
        for recipe in recipes:
            try:
                hook = recipe()
            except sqlite3.Error as exc:      # a shape we didn't expect
                logger.warning("Home hook %s skipped: %s", recipe.__name__, exc)
                hook = None
            if hook:
                hooks.append(hook)
            if len(hooks) >= limit:
                break
        return hooks

    def _hook_fell_out_of_the_league(self) -> dict | None:
        """
        The longest fall the pyramid allows: the top flight, then out of the
        Football League altogether.

        Tier 1 here is the Premier League - the standings begin in 1993/94 -
        and tier 5 is the National League, outside the Football League. So
        the finding is simply a club with a tier-1 season and a later tier-5
        one. The ordering matters and is the whole claim: Luton Town also
        span both tiers, but their fifth-tier seasons came before their
        top-flight one, which is a rise, not a fall.

        Two honesty notes, since this prints the word "only".

        Tier-5 coverage starts in 2005/06 rather than 1993/94, so a club that
        left the Football League between 1994 and 2005 would be invisible
        here. None of the clubs that did - Halifax, Chester, Barnet, Exeter,
        Shrewsbury, York, Carlisle, Kidderminster, Cambridge United - had
        played in the Premier League, so the answer is right; but it rests on
        that window, and the code should say so rather than leave it to be
        rediscovered.

        And the recipe retires its own claim. If a second club ever qualifies
        the sentence becomes a count and the link moves to the page listing
        them all, so no deploy can leave a stale "only club" on the front
        page.
        """
        rows = self.conn.execute(
            """
            SELECT t.canonical_name AS name, s.club_id AS club_id,
                   t.current_tier   AS now_tier,
                   MIN(CASE WHEN s.tier = 1 THEN s.season_end_year END) AS first_top,
                   MIN(CASE WHEN s.tier = 5 THEN s.season_end_year END) AS first_fifth
            FROM standings s
            JOIN club_trajectory t ON t.club_id = s.club_id
            GROUP BY s.club_id
            HAVING first_top IS NOT NULL AND first_fifth IS NOT NULL
               AND first_fifth > first_top
            ORDER BY first_fifth, s.club_id
            """
        ).fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            return {
                "text": (f"{len(rows)} clubs here have played in the Premier "
                         f"League and later dropped out of the Football League"),
                "label": "Every top-flight club that fell, and how far",
                "path": "insights/fallen-giants/index.html",
            }

        row = rows[0]
        # club_trajectory, not club_master: only a club with a trajectory row
        # gets a team page, so joining that way is what makes the link resolve.
        if not row["club_id"]:
            return None
        now = TIER_SLUGS.get(row["now_tier"])
        gap = row["first_fifth"] - row["first_top"]
        label = (f"{season_label(row['first_top'])} to "
                 f"{season_label(row['first_fifth'])}")
        if now:
            label += f", and back in {now[1]} now"
        return {
            "text": (f"{row['name']} went from the Premier League to non-league "
                     f"football in {gap} seasons — the only club here to make "
                     f"that fall"),
            "label": label,
            "path": f"team/{row['club_id']}/index.html",
        }

    def _hook_wage_ratio(self) -> dict | None:
        """Wages above turnover - the overreach that precedes the trouble."""
        path = self._metric_landing_path("wage-ratio") if self._has_finances() else None
        if not path:
            return None
        row = self.conn.execute(
            """
            SELECT t.canonical_name AS name, f.season_end_year AS year,
                   f.turnover AS turnover, f.staff_costs AS staff_costs
            FROM club_finances f
            JOIN club_trajectory t ON t.club_id = f.club_id
            WHERE f.turnover > 0 AND f.staff_costs > 0
            ORDER BY CAST(f.staff_costs AS REAL) / f.turnover DESC, f.club_id
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        ratio = 100.0 * row["staff_costs"] / row["turnover"]
        if ratio < 100:
            # Below 100% this is a chart, not a headline.
            return None
        return {
            "text": (f"{row['name']} paid {ratio:.0f}% of everything they earned "
                     f"straight back out in wages"),
            "label": (f"{_fmt_money(row['staff_costs'])} of "
                      f"{_fmt_money(row['turnover'])}, {season_label(row['year'])}"),
            "path": path,
        }

    def _hook_biggest_loss(self) -> dict | None:
        path = self._metric_landing_path("profit") if self._has_finances() else None
        if not path:
            return None
        row = self.conn.execute(
            """
            SELECT t.canonical_name AS name, f.season_end_year AS year,
                   f.profit_before_tax AS pbt
            FROM club_finances f
            JOIN club_trajectory t ON t.club_id = f.club_id
            WHERE f.profit_before_tax IS NOT NULL AND f.profit_before_tax < 0
            ORDER BY f.profit_before_tax ASC, f.club_id
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        return {
            "text": (f"{row['name']} lost {_fmt_money(abs(row['pbt']))} before tax "
                     f"in a single year"),
            "label": f"{season_label(row['year'])} accounts",
            "path": path,
        }

    def _hook_outspender(self) -> dict | None:
        """
        A club paying more in wages than clubs a division above it. Counted
        only against the clubs in that division whose accounts we hold, and
        the sentence says so - the same honest denominator the club-page
        finance ranks use.
        """
        path = self._metric_landing_path("wages") if self._has_finances() else None
        if not path:
            return None
        row = self.conn.execute(
            """
            SELECT t.canonical_name AS name, f.season_end_year AS year,
                   f.staff_costs AS wages, s.division_name AS division,
                   (SELECT COUNT(*) FROM club_finances f2
                      JOIN standings s2 ON s2.club_id = f2.club_id
                       AND s2.season_end_year = f2.season_end_year
                     WHERE f2.season_end_year = f.season_end_year
                       AND s2.tier = s.tier - 1
                       AND f2.staff_costs IS NOT NULL
                       AND f2.staff_costs < f.staff_costs) AS beaten,
                   (SELECT COUNT(*) FROM club_finances f3
                      JOIN standings s3 ON s3.club_id = f3.club_id
                       AND s3.season_end_year = f3.season_end_year
                     WHERE f3.season_end_year = f.season_end_year
                       AND s3.tier = s.tier - 1
                       AND f3.staff_costs IS NOT NULL) AS above_total
            FROM club_finances f
            JOIN club_trajectory t ON t.club_id = f.club_id
            JOIN standings s ON s.club_id = f.club_id
                            AND s.season_end_year = f.season_end_year
            WHERE f.staff_costs IS NOT NULL AND s.tier > 1
            ORDER BY beaten DESC, f.staff_costs DESC, f.club_id
            LIMIT 1
            """
        ).fetchone()
        if not row or not row["beaten"]:
            return None
        return {
            "text": (f"{row['name']} outspent {row['beaten']} of the "
                     f"{row['above_total']} clubs a division above them on wages"),
            "label": (f"{_fmt_money(row['wages'])} in {row['division']}, "
                      f"{season_label(row['year'])}"),
            "path": path,
        }

    def _hook_points_relegated(self) -> dict | None:
        """
        The biggest points total that still went down.

        Only honest once points deductions are applied: standings.points is
        wins*3 + draws, so before deductions were loaded this returned
        sanctioned clubs - Wigan on 59 having finished 13th - dressed up as
        unlucky relegations. With deductions in, points is the final total
        and the answer is a club that really did need more.
        """
        source = PROJECT_ROOT / "content" / "insights" / "safe-thresholds.md"
        if not source.exists():
            return None
        row = self.conn.execute(
            """
            SELECT club_name AS name, season_end_year AS year,
                   division_name AS division, points AS points,
                   position AS position
            FROM standings
            WHERE status = 'Relegated' AND played >= 30
              AND COALESCE(points_deducted, 0) = 0
              AND COALESCE(data_complete, 1) = 1
            ORDER BY points DESC, club_name
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        return {
            "text": (f"{row['name']} went down with {row['points']} points — "
                     f"the highest total ever relegated here"),
            "label": (f"{row['division']}, {season_label(row['year'])}, "
                      f"finished {_ordinal(row['position'])}"),
            "path": "insights/safe-thresholds/index.html",
        }

    def _hook_longest_stay(self) -> dict | None:
        if "current_tier_streak" not in self.trajectory_cols:
            return None
        row = self.conn.execute(
            """
            SELECT canonical_name AS name, current_tier_streak AS streak
            FROM club_trajectory
            WHERE current_tier = 1 AND current_tier_streak IS NOT NULL
            ORDER BY current_tier_streak DESC, canonical_name
            LIMIT 1
            """
        ).fetchone()
        if not row or not row["streak"] or row["streak"] < 5:
            return None
        return {
            "text": (f"{row['name']} have never once left the top flight in "
                     f"{row['streak']} seasons"),
            "label": "Who stayed up, who fell, and how far",
            "path": "insights/fallen-giants/index.html",
        }

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
                    "in_progress": any(
                        r["status"] == IN_PROGRESS_STATUS for r in rows
                    ),
                    "rows": [_row_dict(r) for r in rows],
                    "has_deductions": any(
                        _row_dict(r)["points_deducted"] for r in rows
                    ),
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
        # club_master, not trajectories: a rivalries: opponent may be a
        # club with no standings row in the tracked tiers (see
        # _rivalry_pairs), but every club with a content file is in
        # club_master.
        club_names = dict(self.conn.execute(
            "SELECT club_id, canonical_name FROM club_master"
        ))

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
                facts_rows = _facts_rows(club_content["facts"], club_names)
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
                finances=self._club_finances(club_id),
                seasons=seasons,
                seasons_have_deductions=any(d["points_deducted"] for d in seasons),
            )

            teams_meta.append({
                "club_id": club_id,
                "name": t["canonical_name"],
                "tier": t["current_tier"],
                "tier_label": TIER_SLUGS.get(t["current_tier"], (None, f"Tier {t['current_tier']}"))[1],
                "color": self.color(club_id),
                "search_key": _search_key(t["canonical_name"]),
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
        """
        Two kinds of thing live under /insights/: pages that make an
        argument in prose and tables, and charts you drive yourself. They
        used to render as one flat grid of fifteen tiles, which buried ten
        distinct stories among five tiles that were the same scatter chart
        with a different metric selected - a page that already carries
        chips to switch metric in place.
        """
        def story(slug: str, name: str, sub: str) -> dict:
            return {"slug": slug, "name": name, "sub": sub,
                    "path": f"insights/{slug}/index.html"}

        stories = [
            story("yo-yo", "Yo-yo clubs", "The volatility league"),
            story("fallen-giants", "Fallen giants & risers",
                  "Long falls and great climbs"),
            story("records", "Records & extremes", "The best and worst seasons"),
            story("timeline", "Timeline", "Notable events since 1993"),
        ]
        if "natural_level_gap" in self.trajectory_cols:
            stories.insert(1, story(
                "natural-level", "Above and below their level",
                "Clubs out of step with their own history",
            ))
        if (PROJECT_ROOT / "content" / "insights" / "safe-thresholds.md").exists():
            stories.append(story(
                "safe-thresholds", "Safe thresholds",
                "The points needed to survive relegation",
            ))
        boom_bust_events = self._boom_bust_events()
        if boom_bust_events:
            stories.append(story(
                "boom-and-bust", "Boom and bust",
                "Why the same clubs keep falling into financial trouble",
            ))
        rivalries = self._rivalry_pairs()
        if rivalries:
            stories.append(story(
                "rivalries", "Rivalries & derbies",
                "The needle behind the fixture list",
            ))
        movement_matches = self._movement_matches()
        import movement as movement_mod
        if any(movement_matches.get(k) for k in (
            movement_mod.RELEGATION_BACK_TO_BACK, movement_mod.RELEGATION_THREE_PLUS,
            movement_mod.RELEGATION_HELD, movement_mod.RELEGATION_SANDWICH,
        )):
            stories.append(story(
                "the-drop", "The drop",
                "Clubs that fell fast — and whether they came back",
            ))
        if any(movement_matches.get(k) for k in (
            movement_mod.PROMOTION_BACK_TO_BACK, movement_mod.PROMOTION_THREE_PLUS,
            movement_mod.PROMOTION_PAUSED,
        )):
            stories.append(story(
                "the-rise", "The rise",
                "Clubs that climbed fast — and whether they held on",
            ))

        # Chart tiles link through _metric_landing_path rather than to
        # base/index.html, which only exists for the current season.
        charts = []
        capacity_path = self._metric_landing_path("capacity")
        if capacity_path:
            charts.append({
                "slug": "capacity",
                "name": METRICS["capacity"]["heading"],
                "sub": METRICS["capacity"]["sub"],
                "path": capacity_path,
            })
        # One tile for all five financial metrics: they are a single page
        # with chips to switch between them, so five tiles was one idea
        # taking a third of the index. Prefers revenue, falling back to
        # whichever financial metric has data.
        finance_path = next(
            (path for path in (
                self._metric_landing_path(key)
                for key, metric in METRICS.items() if metric["source"] == "finances"
            ) if path),
            None,
        )
        if finance_path:
            charts.append({
                "slug": "finances",
                "name": "Club finances",
                "sub": "Revenue, wages, profit and debt against where clubs finish",
                "path": finance_path,
            })

        groups = [g for g in (
            {"title": "Stories",
             "sub": "Arguments drawn from thirty years of league tables.",
             "entries": stories},
            {"title": "Interactive charts",
             "sub": "Pick a metric and a season, then read the pyramid.",
             "entries": charts},
        ) if g["entries"]]

        self.render(
            "insights_index.html", self.out / "insights" / "index.html", 1,
            title="Insights", groups=groups, entries=stories + charts,
        )
        self._insight_yo_yo()
        self._insight_natural_level()
        self._insight_fallen_giants()
        self._insight_records()
        self._insight_safe_thresholds()
        self._insight_timeline()
        self._insight_scatter()
        self._insight_boom_and_bust(boom_bust_events)
        self._insight_the_drop(movement_matches)
        self._insight_the_rise(movement_matches)
        self._insight_rivalries(rivalries)

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

    def _rivalry_pairs(self) -> list[dict]:
        """
        One entry per documented rivalry, deduped by the unordered pair of
        clubs involved - a derby is sometimes written up from only one
        side's file, occasionally from both. Where both sides wrote an
        entry, the one with a note (or the longer note) wins, since that's
        the more useful account to show; the other is dropped silently
        rather than shown twice.
        """
        # club_master, not club_trajectory: a rivalry's opponent may be a
        # club with no standings row in the tracked tiers at all (Bradford
        # Park Avenue hasn't played in Tiers 1-5 since before the 1993/94
        # data start), but every club with a content file is in club_master.
        names = dict(self.conn.execute(
            "SELECT club_id, canonical_name FROM club_master"
        ))

        by_pair: dict[frozenset, dict] = {}
        for club_id, facts in self.club_facts.items():
            for rivalry in (facts.get("rivalries") or []):
                if not isinstance(rivalry, dict) or not rivalry.get("opponent"):
                    continue
                opponent = rivalry["opponent"]
                if opponent not in names:
                    logger.warning(
                        "%s: rivalry opponent %r is not a known club_id - skipping",
                        club_id, opponent,
                    )
                    continue
                pair = frozenset((club_id, opponent))
                entry = {
                    "club_a": club_id, "name_a": names.get(club_id, club_id),
                    "club_b": opponent, "name_b": names[opponent],
                    "name": rivalry.get("name"),
                    "note": rivalry.get("note") or "",
                }
                existing = by_pair.get(pair)
                if existing is None or len(entry["note"]) > len(existing["note"]):
                    by_pair[pair] = entry

        return sorted(by_pair.values(), key=lambda e: (e["name_a"], e["name_b"]))

    def _insight_rivalries(self, rivalries: list[dict]) -> None:
        if not rivalries:
            return

        clubs_involved = {e["club_a"] for e in rivalries} | {e["club_b"] for e in rivalries}
        stats = [
            {"value": len(rivalries), "label": "Documented rivalries"},
            {"value": len(clubs_involved), "label": "Clubs involved"},
        ]

        # Only link a club that actually has a team page - build_teams()
        # renders one per club_trajectory row, which is every club with
        # standings data in the tracked tiers, not every club_master entry
        # (e.g. Bradford Park Avenue has a story file but no page, since it
        # hasn't played Tiers 1-5 since before the 1993/94 data start).
        has_page = {r[0] for r in self.conn.execute("SELECT club_id FROM club_trajectory")}

        rows = [
            [self._cell(e["name"] or f"{e['name_a']} – {e['name_b']}"),
             self._cell(e["name_a"], e["club_a"] if e["club_a"] in has_page else None),
             self._cell(e["name_b"], e["club_b"] if e["club_b"] in has_page else None),
             self._cell(e["note"])]
            for e in rivalries
        ]

        self.render(
            "insight_table.html", self.out / "insights" / "rivalries" / "index.html", 2,
            title="Rivalries & derbies",
            heading="Rivalries & derbies",
            intro=(
                "Local grudges, spite nicknames and boardroom feuds - the needle "
                "behind the fixture list."
            ),
            stats=stats,
            sections=[{
                "columns": ["Derby", "Club", "Club", "What's behind it"],
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

    def _has_finances(self) -> bool:
        """
        The committed database can predate club_finances, so the financial
        metrics degrade to absent rather than raising - same approach as
        trajectory_cols for the natural-level columns.
        """
        if self._finances_table is None:
            self._finances_table = bool(self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='club_finances'"
            ).fetchone())
        return self._finances_table

    def _finance_ranks(self) -> dict:
        """
        {(club_id, season): {"turnover": (rank, total, division), ...}} -
        where a club's money sits among the clubs it actually played
        against that season.

        The denominator is the clubs with a *published* figure, not the
        clubs in the division. Coverage is partial by design (deliberate
        omissions, small-company filings, clubs not yet researched), so a
        rank of "4th of 19" in a 24-club division is the honest form and
        the template says so; presenting it as 4th of 24 would invent
        coverage that doesn't exist.

        Built in one pass rather than a query per club, since build_teams
        walks every club in the database.
        """
        if self._finance_ranks_cache is not None:
            return self._finance_ranks_cache

        ranks: dict = {}
        if not self._has_finances():
            self._finance_ranks_cache = ranks
            return ranks

        # A club-season with no standings row in tiers 1-5 has no division
        # to be ranked within, so the join drops it rather than ranking it
        # against an unrelated set.
        rows = self.conn.execute(
            """
            SELECT f.club_id, f.season_end_year, s.tier, s.division_name,
                   f.turnover, f.staff_costs
            FROM club_finances f
            JOIN standings s
              ON s.club_id = f.club_id AND s.season_end_year = f.season_end_year
            WHERE f.disclosure = 'full'
            """
        ).fetchall()

        groups: dict = {}
        for club_id, year, tier, division_name, turnover, staff_costs in rows:
            for field, value in (("turnover", turnover), ("staff_costs", staff_costs)):
                if value is None:
                    continue
                groups.setdefault((year, tier, field), []).append(
                    (club_id, float(value), division_name)
                )

        for (year, _tier, field), entries in groups.items():
            total = len(entries)
            values = [v for _cid, v, _dn in entries]
            for club_id, value, division_name in entries:
                # Ties share a rank: two clubs on the same turnover are
                # both "4th", not 4th and 5th in arbitrary order.
                rank = 1 + sum(1 for other in values if other > value)
                ranks.setdefault((club_id, year), {})[field] = (
                    rank, total, division_name
                )

        self._finance_ranks_cache = ranks
        return ranks

    def _club_finances(self, club_id: str) -> dict | None:
        """
        The finance table for one club's page, or None when the club has
        no rows at all - so the section disappears entirely rather than
        rendering an empty shell, matching has_chart/club_themes.
        """
        if not self._has_finances():
            return None

        raw = self.conn.execute(
            """
            SELECT season_end_year, disclosure, turnover, staff_costs,
                   staff_costs_definition, profit_before_tax, net_debt,
                   entity_name, period_months, source_url, flags
            FROM club_finances
            WHERE club_id = ?
            ORDER BY season_end_year DESC
            """,
            (club_id,),
        ).fetchall()
        if not raw:
            return None

        ranks = self._finance_ranks()
        rows, flags_seen, seasons_with_value = [], set(), {}

        def rank_cell(field, year):
            entry = ranks.get((club_id, year), {}).get(field)
            if not entry:
                return None
            rank, total, division_name = entry
            noun = "turnover" if field == "turnover" else "wage bill"
            # "1st highest" reads badly; the top of the table is just "highest".
            place = "Highest" if rank == 1 else f"{_ordinal(rank)} highest"
            return {
                "short": f"{_ordinal(rank)} of {total}",
                "title": (
                    f"{place} {noun} of the {total} clubs with published figures "
                    f"in {division_name}, {season_label(year)}"
                ),
            }

        for (year, disclosure, turnover, staff_costs, definition,
             profit, net_debt, entity_name, period_months,
             source_url, flags_json) in raw:
            for flag in _parse_flags(flags_json):
                if flag in FLAG_LABELS:
                    flags_seen.add(flag)

            row = {
                "season_label": season_label(year),
                "season_end_year": year,
                "entity_name": entity_name,
                "source_url": source_url,
                "disclosure_note": DISCLOSURE_NOTES.get(disclosure),
            }
            if disclosure == finances.DISCLOSURE_FULL:
                row.update({
                    "turnover": _fmt_money(turnover) if turnover is not None else None,
                    "turnover_rank": rank_cell("turnover", year),
                    "staff_costs": (
                        _fmt_money(staff_costs) if staff_costs is not None else None
                    ),
                    "staff_costs_rank": rank_cell("staff_costs", year),
                    "wage_ratio": (
                        f"{staff_costs / turnover * 100:.0f}%"
                        if staff_costs is not None and turnover else None
                    ),
                    "profit": (
                        _fmt_money(profit) if profit is not None else None
                    ),
                    "profit_negative": profit is not None and profit < 0,
                    "net_debt": _fmt_money(net_debt) if net_debt is not None else None,
                })
                for field, value in (("turnover", turnover),
                                     ("staff_costs", staff_costs),
                                     ("profit_before_tax", profit),
                                     ("net_debt", net_debt)):
                    if value is not None:
                        seasons_with_value.setdefault(field, []).append(year)
                if period_months and period_months != 12:
                    row["period_note"] = f"{period_months}-month period"
            rows.append(row)

        return {
            "rows": rows,
            "notes": [FLAG_LABELS[f] for f in sorted(flags_seen)],
            "chart_links": self._finance_chart_links(seasons_with_value),
        }

    def _finance_chart_links(self, seasons_with_value: dict) -> list[dict]:
        """
        Back into the scatter charts, but only for metrics this club has a
        value for - a link to a chart the club isn't plotted on is a dead
        end dressed up as a route.
        """
        links = []
        for key, metric in METRICS.items():
            if metric["source"] != "finances":
                continue
            years = seasons_with_value.get(metric["field"])
            if metric["field"] == "wage_ratio":
                # Derived: needs both, so it inherits the wage bill's seasons.
                years = seasons_with_value.get("staff_costs")
            if not years:
                continue
            links.append({
                "label": metric["label"],
                "path": f"{metric['base']}/{season_slug(max(years))}/index.html",
            })
        return links

    def _metric_values(self, metric_key: str, season_end_year: int) -> dict[str, dict]:
        """
        {club_id: {"value": float, "extra": {...}}} for one metric in one
        season. Only clubs with a real figure are returned; non-disclosure
        is counted separately by _disclosure_counts() rather than plotted.
        """
        metric = METRICS[metric_key]

        if metric["source"] == "facts":
            # Not season-scoped: a ground's capacity is one fact in the club's
            # story front-matter, so the same value appears on every season's
            # page and only the plotted position moves.
            return {
                cid: {"value": float(facts[metric["field"]]), "extra": {}}
                for cid, facts in self.club_facts.items()
                if isinstance(facts.get(metric["field"]), (int, float))
            }

        if not self._has_finances():
            return {}

        rows = self.conn.execute(
            """
            SELECT club_id, turnover, staff_costs, profit_before_tax, net_debt,
                   revenue_matchday, revenue_broadcast, revenue_commercial,
                   staff_costs_definition, entity_name, period_months
            FROM club_finances
            WHERE season_end_year = ? AND disclosure = 'full'
            """,
            (season_end_year,),
        ).fetchall()

        field = metric["field"]
        values: dict[str, dict] = {}
        for (club_id, turnover, staff_costs, profit, net_debt,
             matchday, broadcast, commercial, definition,
             entity_name, period_months) in rows:
            if field == "wage_ratio":
                if not turnover or staff_costs is None:
                    continue
                value = staff_costs / turnover * 100
            else:
                raw = {
                    "turnover": turnover,
                    "staff_costs": staff_costs,
                    "profit_before_tax": profit,
                    "net_debt": net_debt,
                }[field]
                if raw is None:
                    continue
                value = float(raw)

            extra = {}
            if field == "turnover" and any(
                x is not None for x in (matchday, broadcast, commercial)
            ):
                parts = [
                    (name, amount)
                    for name, amount in (("matchday", matchday),
                                         ("broadcast", broadcast),
                                         ("commercial", commercial))
                    if amount is not None
                ]
                extra["breakdown"] = " · ".join(
                    f"{name} {_fmt_money(amount)}" for name, amount in parts
                )
            if field in ("staff_costs", "wage_ratio") and definition:
                extra["definition"] = definition.replace("_", " ")
            # A period that isn't 12 months long isn't comparable with one
            # that is, so say so rather than letting it pass as like-for-like.
            if period_months and period_months != 12:
                extra["period"] = f"{period_months}-month period"
            if entity_name:
                extra["entity"] = entity_name

            values[club_id] = {"value": value, "extra": extra}
        return values

    def _disclosure_counts(self, season_end_year: int) -> dict:
        """
        How many clubs in a season published figures at all. A club filing
        under the small-company regime hasn't gone missing - it has declined
        to say - and that distinction is worth showing rather than hiding in
        a gap on the chart.
        """
        in_season = self.conn.execute(
            "SELECT COUNT(*) FROM standings WHERE season_end_year = ? AND tier <= 5",
            (season_end_year,),
        ).fetchone()[0]
        if not self._has_finances():
            return {"in_season": in_season, "disclosed": 0, "withheld": 0}

        rows = dict(self.conn.execute(
            """
            SELECT CASE WHEN disclosure = 'full' THEN 'disclosed' ELSE 'withheld' END,
                   COUNT(*)
            FROM club_finances WHERE season_end_year = ? GROUP BY 1
            """,
            (season_end_year,),
        ).fetchall())
        return {
            "in_season": in_season,
            "disclosed": rows.get("disclosed", 0),
            "withheld": rows.get("withheld", 0),
        }

    def _metric_points(self, metric_key: str, season_end_year: int) -> list[dict]:
        key = (metric_key, season_end_year)
        if key not in self._metric_points_cache:
            self._metric_points_cache[key] = self._compute_metric_points(
                metric_key, season_end_year
            )
        return self._metric_points_cache[key]

    def _metric_landing_path(self, metric_key: str) -> str | None:
        """
        Where a link to this metric should actually point.

        The scatter pages are a metric x season matrix, and only the
        *current* season is written to the bare base URL - every older
        season lives under base/<season>/. So base/index.html is a 404 for
        any metric whose newest data predates the current season, which is
        every financial metric the moment a new season kicks off: 2026/27
        exists in standings before a single set of accounts covers it.
        That was live on the insights index - all five finance tiles led
        nowhere. Returns the newest season page that was actually built, or
        None when the metric has no data at all.
        """
        base = METRICS[metric_key]["base"]
        current_year = self.seasons[-1]
        for year in reversed(self.seasons[-6:]):
            if self._metric_points(metric_key, year):
                if year == current_year:
                    return f"{base}/index.html"
                return f"{base}/{season_slug(year)}/index.html"
        return None

    def _compute_metric_points(self, metric_key: str, season_end_year: int) -> list[dict]:
        """
        One plottable point per club that has both a value for this metric
        and a Tier 1-5 standings row in this season. A club outside the
        covered pyramid that season simply has no row and is left out.
        """
        values = self._metric_values(metric_key, season_end_year)
        if not values:
            return []

        placeholders = ",".join("?" * len(values))
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
              AND s.season_end_year = ?
            """,
            list(values) + [season_end_year],
        ).fetchall()

        names = dict(self.conn.execute("SELECT club_id, canonical_name FROM club_trajectory"))
        fmt = METRICS[metric_key]["format"]
        points = []
        for club_id, tier, position, overall_pos in rows:
            entry = values[club_id]
            points.append({
                "club_id": club_id,
                "name": names.get(club_id, club_id),
                "color": self.color(club_id),
                "tier": tier,
                "division_name": TIER_SLUGS.get(tier, (None, f"Tier {tier}"))[1],
                "position": position,
                "overall_pos": overall_pos,
                "value": entry["value"],
                "value_label": fmt(entry["value"]),
                "extra": entry["extra"],
            })
        return sorted(points, key=lambda p: p["overall_pos"])

    # Kept as a thin alias: the insights index and its tests refer to the
    # capacity chart by name, and it is still the metric linked from there.
    def _capacity_points(self, season_end_year: int) -> list[dict]:
        return self._metric_points(LEGACY_METRIC, season_end_year)

    @staticmethod
    def _y_axis(values: list[float], scale: str):
        """
        (fraction_of_height_fn, min_label_value, max_label_value,
        zero_fraction, inverse_fn).

        zero_fraction is None unless the axis spans zero and a zero line is
        meaningful - only the signed scales, where a loss below the line is
        the whole point. inverse_fn maps a height-fraction back to a raw
        value - the mirror of the fraction fn - used to place intermediate
        y-axis tick labels without duplicating the padding/domain logic per
        scale; the client-side tier filter also ports this same function to
        rescale the axes to only the visible points (see static/insight-scatter.js).
        """
        lo, hi = min(values), max(values)

        if scale == "log":
            lo_l, hi_l = math.log10(lo), math.log10(hi)
            pad = max(0.05, (hi_l - lo_l) * 0.08)
            lo_l, hi_l = lo_l - pad, hi_l + pad
            span = max(1e-9, hi_l - lo_l)
            return (lambda v: (math.log10(v) - lo_l) / span,
                    10 ** lo_l, 10 ** hi_l, None,
                    lambda t: 10 ** (lo_l + t * span))

        if scale == "signed":
            lo, hi = min(lo, 0.0), max(hi, 0.0)
            pad = max(1.0, (hi - lo) * 0.08)
            lo, hi = lo - pad, hi + pad
            span = max(1e-9, hi - lo)
            frac = lambda v: (v - lo) / span  # noqa: E731
            return frac, lo, hi, frac(0.0), lambda t: lo + t * span

        # Linear. Clamped at zero when every value is positive, because a
        # stadium can't hold a negative number of people and with few points
        # the padded minimum would otherwise cross zero.
        pad = max(1, round((hi - lo) * 0.08))
        lo = max(0, lo - pad) if lo >= 0 else lo - pad
        hi = hi + pad
        span = max(1e-9, hi - lo)
        return (lambda v: (v - lo) / span), lo, hi, None, lambda t: lo + t * span

    def _insight_scatter(self) -> None:
        """
        Renders the metric x season matrix of scatter pages. Capacity keeps
        its original /insights/capacity/ URLs, since the insights index links
        there; the financial metrics live under /insights/finances/<metric>/.
        Each page carries chips for both axes of the matrix, and a metric or
        season with nothing to plot is skipped rather than rendered empty.
        """
        import charts as charts_mod
        import json

        candidate_years = list(reversed(self.seasons[-6:]))  # current, then up to 5 prior
        floors_by_year, max_pos = charts_mod.tier_floors(self.conn)
        total_clubs = self.conn.execute("SELECT COUNT(*) FROM club_master").fetchone()[0]
        current_year = self.seasons[-1]

        # Gather everything first: a metric with no data anywhere gets no
        # chip, so the chip row never links to a page that doesn't exist.
        plotted: dict[str, dict[int, list[dict]]] = {}
        for key in METRICS:
            by_year = {}
            for year in candidate_years:
                points = self._metric_points(key, year)
                if points:
                    by_year[year] = points
            if by_year:
                plotted[key] = by_year
        if not plotted:
            return

        def page_path(metric_key: str, year: int) -> str:
            base = METRICS[metric_key]["base"]
            if year == current_year:
                return f"{base}/index.html"
            return f"{base}/{season_slug(year)}/index.html"

        for key, by_year in plotted.items():
            metric = METRICS[key]
            season_tabs_all = [
                {"label": season_label(y), "path": page_path(key, y), "year": y}
                for y in by_year
            ]

            for year, points in by_year.items():
                boundaries = floors_by_year.get(year, [])
                values = [p["value"] for p in points]
                frac, y_lo, y_hi, zero_frac, inverse = self._y_axis(values, metric["scale"])

                W, H = 760, 380
                PAD = {"top": 16, "right": 20, "bottom": 36, "left": 64}
                span_x = max(1, max_pos - 1)
                plot_h = H - PAD["top"] - PAD["bottom"]

                def x(pos, span_x=span_x):
                    return PAD["left"] + (pos - 1) / span_x * (W - PAD["left"] - PAD["right"])

                def y(value, frac=frac, plot_h=plot_h):
                    return PAD["top"] + (1 - frac(value)) * plot_h

                for p in points:
                    p["cx"] = round(x(p["overall_pos"]), 1)
                    p["cy"] = round(y(p["value"]), 1)
                    bits = [
                        f"{p['name']} — {p['division_name']}, position {p['position']}",
                        f"{p['value_label']} {metric['noun']}",
                    ]
                    extra = p["extra"]
                    for detail_key in ("breakdown", "definition", "period", "entity"):
                        if extra.get(detail_key):
                            bits.append(extra[detail_key])
                    p["tooltip"] = " — ".join(bits[:2]) + (
                        f" ({'; '.join(bits[2:])})" if len(bits) > 2 else ""
                    )

                fmt = metric["format"]
                zero_y = round(PAD["top"] + (1 - zero_frac) * plot_h, 1) if zero_frac is not None else None
                benchmark = metric.get("benchmark")
                benchmark_y = None
                if benchmark and y_lo <= benchmark["value"] <= y_hi:
                    benchmark_y = round(y(benchmark["value"]), 1)

                # Intermediate labels between the existing min/max - purely
                # a readability aid, so evenly-spaced height-fractions are
                # enough; no need for "nice round number" tick placement.
                y_ticks = [
                    {"y": round(PAD["top"] + (1 - t) * plot_h, 1), "label": fmt(inverse(t))}
                    for t in (0.25, 0.5, 0.75)
                ]

                counts = self._disclosure_counts(year)
                if metric["source"] == "finances":
                    provenance = (
                        f"Figures for {len(points)} of {counts['in_season']} clubs in "
                        f"{season_label(year)}, taken from accounts filed at Companies "
                        f"House. {counts['withheld']} filed accounts that do not "
                        f"disclose the figure; the rest are not yet researched."
                    )
                else:
                    provenance = (
                        f"Ground capacity from the club stories written so far "
                        f"({len(points)} of {total_clubs} clubs)."
                    )

                is_current = year == current_year
                out_path = self.out / page_path(key, year)
                depth = len(Path(page_path(key, year)).parts) - 1
                legend = [{"tier": t, "name": name, "key": t}
                          for t, (_slug, name) in TIER_SLUGS.items()]

                self.render(
                    "insight_scatter.html", out_path, depth,
                    title=f"{metric['heading']} — {season_label(year)}",
                    heading=metric["heading"],
                    season_label=season_label(year),
                    metric_tabs=[
                        {"label": METRICS[k]["label"],
                         "path": page_path(k, year if year in plotted[k] else max(plotted[k])),
                         "active": k == key}
                        for k in plotted
                    ],
                    season_tabs=[
                        {"label": t["label"], "path": t["path"], "active": t["year"] == year}
                        for t in season_tabs_all
                    ],
                    intro=(
                        f"{provenance} Plotted against each club's overall position "
                        f"across all five tiers in {season_label(year)}. Dashed lines "
                        f"mark the boundary between divisions."
                    ),
                    points=points,
                    boundary_lines=[round(x(b + 0.5), 1) for b in boundaries],
                    width=W, height=H,
                    plot_top=PAD["top"], plot_bottom=H - PAD["bottom"],
                    axis_y=H - PAD["bottom"] + 16,
                    x_min_label=1, x_max_label=max_pos,
                    y_min_label=fmt(y_lo), y_max_label=fmt(y_hi),
                    y_ticks=y_ticks,
                    zero_line_y=zero_y,
                    benchmark_line_y=benchmark_y,
                    benchmark_label=benchmark["label"] if benchmark_y else None,
                    legend=legend,
                    tier_chips=legend,
                )

                # Sibling data file: lets static/insight-scatter.js rebuild
                # the whole chart client-side (tier filter, axis rescale,
                # click detail) without a page reload. Written after
                # render() so the output directory already exists.
                payload = {
                    "scale": metric["scale"],
                    "formatKind": metric["format_kind"],
                    "noun": metric["noun"],
                    "maxPos": max_pos,
                    "boundaries": boundaries,
                    "benchmarkValue": benchmark["value"] if benchmark else None,
                    "benchmarkLabel": benchmark["label"] if benchmark else None,
                    "seasonLabel": season_label(year),
                    "points": [
                        {
                            "id": p["club_id"], "name": p["name"], "color": p["color"],
                            "tier": p["tier"], "divisionName": p["division_name"],
                            "position": p["position"], "overallPos": p["overall_pos"],
                            "value": p["value"], "valueLabel": p["value_label"],
                            "tooltip": p["tooltip"],
                        }
                        for p in points
                    ],
                }
                (out_path.parent / "insight-scatter-data.js").write_text(
                    "window.INSIGHT_SCATTER_DATA = " + json.dumps(payload) + ";",
                    encoding="utf-8",
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

    def _standings_section(
        self, heading: str, note: str, order: str, limit: int = 10,
        where: str = "s.played >= 30", include_status: bool = False,
    ) -> dict:
        """
        A "most/fewest X" style table. order/limit/where pick the rows -
        that's the actual selection, e.g. the 10 most extreme points
        totals across every division and era.
        """
        cols = ("s.club_id, s.club_name, s.season_end_year, s.division_name, "
                "s.tier, s.position, s.points, s.gd")
        if include_status:
            cols += ", s.status"

        # Completeness is enforced here rather than left to each caller: a
        # superlative drawn from a table missing a chunk of its fixtures is
        # not a record, it's an artifact. Twenty-odd season/division tables
        # are affected (see pipeline._mark_data_completeness) - part-season
        # football-data files, and the 2019/20 divisions abandoned in March
        # 2020. COALESCE keeps a database built before the flag existed
        # working as it did.
        complete_only = (
            " AND COALESCE(s.data_complete, 1) = 1"
            if "data_complete" in self.standings_cols else ""
        )
        rows = self.conn.execute(
            f"""
            SELECT {cols}
            FROM standings s
            WHERE ({where}){complete_only}
            ORDER BY {order} LIMIT {limit}
            """
        ).fetchall()

        columns = ["Club", "Season", "Division", "Pos", "Pts", "GD"]
        if include_status:
            columns = ["Club", "Season", "Division", "Pts", "Status"]

        def _row(r):
            res = [
                self._cell(r["club_name"], r["club_id"]),
                self._cell(season_label(r["season_end_year"])),
                self._cell(r["division_name"]),
            ]
            if include_status:
                res.extend([
                    self._cell(r["points"], num=True),
                    self._cell(r["status"]),
                ])
            else:
                res.extend([
                    self._cell(r["position"], num=True),
                    self._cell(r["points"], num=True),
                    self._cell(r["gd"], num=True),
                ])
            return res

        return {
            "heading": heading,
            "note": note,
            "columns": columns,
            "rows": [_row(r) for r in rows],
        }

    def _insight_records(self) -> None:
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
                self._standings_section("Most points in a season", "Full seasons only.",
                                   "s.points DESC, s.gd DESC"),
                self._standings_section("Fewest points in a season", "The campaigns to forget.",
                                   "s.points ASC, s.gd ASC"),
                self._standings_section("Best goal difference", "", "s.gd DESC, s.points DESC"),
                self._standings_section("Worst goal difference", "", "s.gd ASC, s.points ASC"),
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

    def _insight_safe_thresholds(self) -> None:
        """
        How many points it took to survive - asked separately of the
        38-game Premier League and the 46-game divisions below it.

        A points total is only meaningful against the number of games that
        produced it, so these used to be one table per question with a
        Played column and rows clustered by division: a reader could tell a
        38-game season from a 46-game one, but the ranking itself still
        mixed them and meant nothing. Splitting on games played makes every
        row in a table directly comparable to every other row in it, and
        the ranking honest without any per-row caveat.

        Seasons played over some other number of games are left out
        entirely rather than shown alongside: the 22-club Premier League
        and Third Division of 1993/94 and 1994/95 (42 games), and the two
        23-club National League seasons (44). Within the window this site
        covers, 38 games means the Premier League and nothing else, and 46
        means the four divisions below it and nothing else - so filtering
        on games played says exactly what it means.
        """
        import content as content_mod

        source = PROJECT_ROOT / "content" / "insights" / "safe-thresholds.md"
        if not source.exists():
            return

        top = "Premier League seasons only, which have run to 38 games since 1995/96."
        rest = ("The Championship, League One, League Two and National League, "
                "all of which run to 46 games. Ranked purely on points, since "
                "every row here comes from a season of the same length.")

        self.render(
            "insight_table.html", self.out / "insights" / "safe-thresholds" / "index.html", 2,
            title="Safe thresholds",
            heading="Safe thresholds",
            intro=content_mod.load_theme(source),
            sections=[
                self._standings_section(
                    "Unlucky losers: Premier League", top,
                    "s.points DESC, s.gd ASC", 10,
                    "s.played = 38 AND (s.status = 'Relegated' OR s.status = 'Play-off Relegated')",
                    include_status=True,
                ),
                self._standings_section(
                    "Unlucky losers: the 46-game divisions", rest,
                    "s.points DESC, s.gd ASC", 10,
                    "s.played = 46 AND (s.status = 'Relegated' OR s.status = 'Play-off Relegated')",
                    include_status=True,
                ),
                self._standings_section(
                    "Lucky survivors: Premier League", top,
                    "s.points ASC, s.gd DESC", 10,
                    "s.played = 38 AND s.status = 'Stayed'",
                    include_status=True,
                ),
                self._standings_section(
                    "Lucky survivors: the 46-game divisions", rest,
                    "s.points ASC, s.gd DESC", 10,
                    "s.played = 46 AND s.status = 'Stayed'",
                    include_status=True,
                ),
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
