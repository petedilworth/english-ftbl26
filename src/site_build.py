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

import aggregate  # noqa: E402  (points-era boundary for records tables)
import content  # noqa: E402  (needs _SRC on the path first)
import divisions
import divisions as divisions_mod
import finances  # noqa: E402  (disclosure states for the club finances table)
import historical  # noqa: E402  (why a backfilled table is flagged not-final)

PROJECT_ROOT = _SRC.parent

logger = logging.getLogger(__name__)

# 1992/93, the Premier League's first season. Tier 1 reaches back to
# 1958/59, so anything that means "the Premier League" rather than "the top
# flight" has to say which.
PREMIER_LEAGUE_FROM = 1993

# The single-division tiers, derived from the registry rather than
# restated here. A tier that holds several divisions is deliberately
# absent: it has no one slug and no one name, and the callers below that
# use this are all asking a question about a tier that is a division.
# Division pages themselves are built from divisions.DIVISIONS.
TIER_SLUGS = {
    d.tier: (d.division_id, d.name)
    for d in divisions.DIVISIONS
    if divisions.sole_division(d.tier) is not None
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
    "catchment": {
        "label": "Catchment population",
        "heading": "Catchment population vs. league position",
        "sub": "How many people a club could draw on, after its neighbours take their share",
        "base": "insights/catchment",
        "source": "catchment",
        "field": "catchment_pop_restored",
        "scale": "log",
        "format": lambda v: f"{int(v):,}",
        "format_kind": "count",
        "noun": "catchment",
    },
    "catchment-income": {
        "label": "Catchment income",
        "heading": "Catchment income vs. league position",
        "sub": "What the people in reach earn - modelled by ONS, not measured",
        "base": "insights/catchment/income",
        "source": "catchment",
        "field": "catchment_income",
        "scale": "linear",
        "format": _fmt_money,
        "format_kind": "money",
        "noun": "catchment income",
    },
    "contested": {
        "label": "Catchment contested",
        "heading": "How much of a club's own area is taken by its neighbours",
        "sub": "0% is uncontested ground; 100% is a catchment entirely spoken for",
        "base": "insights/catchment/contested",
        "source": "catchment",
        "field": "contest_ratio",
        "scale": "linear",
        "format": lambda v: f"{v:.0f}%",
        "format_kind": "percent",
        "noun": "contested share",
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


def _distance_phrase(miles: float | None, approximate: bool) -> str | None:
    """
    A distance between two clubs, said to the precision it actually has.

    Eighty clubs sit at the population-weighted centre of their local
    authority rather than at a ground, and that placement is good to a
    median of 1.6 miles. Bury to Radcliffe comes out at 0.5 miles on those
    coordinates; Stainton Park is about three miles from Gigg Lane. So a
    distance to a town-placed club is rounded to the mile and marked, and
    below two miles it is not given as a number at all - the data cannot
    tell nought from three, and a decimal place would say that it can.
    """
    if miles is None:
        return None
    if not approximate:
        return f"{miles:.1f} miles"
    whole = round(miles)
    return "a mile or two" if whole <= 1 else f"~{whole} miles"


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
        # And for club_catchment, which is empty until the demographics
        # CSV lands. Caches whether it has ROWS, not just a table.
        self._catchment_rows: bool | None = None
        # Division ranks for every club-season, built once on first use -
        # build_teams walks every club, so a query per club would be wasteful.
        self._finance_ranks_cache: dict | None = None
        # build_insights, _insight_scatter and the home hooks all ask the
        # same (metric, season) questions, and each answer walks the season.
        self._metric_points_cache: dict = {}
        self.standings_cols = {
            r[1] for r in self.conn.execute("PRAGMA table_info(standings)")
        }
        # Which clubs get a page. club_master holds more clubs than the
        # site renders - the catchment model knows about clubs with
        # coordinates but no standings row, and linking to those produces
        # a page that was never built.
        self.club_pages = {
            r[0] for r in self.conn.execute("SELECT club_id FROM club_trajectory")
        }
        # location_precision arrived with the non-league clubs; a database
        # from before it degrades to treating every coordinate as a ground,
        # which is what it was.
        self.master_cols = {
            r[1] for r in self.conn.execute("PRAGMA table_info(club_master)")
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
        """
        Every division played in a season, in ladder order.

        By DIVISION, not by tier. Keyed on the tier this concatenated the
        National League North and South into one table of forty-four
        clubs with two at every position, labelled with whichever name
        came first, and did the same to three divisions at the seventh
        tier - fourteen season pages, silently, because a table of
        forty-four rows looks like a table.
        """
        divisions_list = []
        keyed_by_division = "division_id" in self.standings_cols
        key = "division_id" if keyed_by_division else "tier"
        found = self.conn.execute(
            f"SELECT DISTINCT tier, {key} FROM standings WHERE season_end_year = ?",
            (year,),
        ).fetchall()

        def order(pair):
            tier, value = pair
            division = divisions_mod.BY_ID.get(value) if keyed_by_division else None
            return (tier, division.sort_order if division else 0)

        for tier, value in sorted(found, key=order):
            rows = self.conn.execute(
                f"""
                SELECT * FROM standings
                WHERE season_end_year = ? AND {key} IS ? ORDER BY position
                """,
                (year, value),
            ).fetchall()
            divisions_list.append({
                "tier": tier,
                "name": rows[0]["division_name"] if rows else TIER_SLUGS[tier][1],
                "rows": [_row_dict(r) for r in rows],
                "coverage_note": self._coverage_note(year, tier, len(rows), value
                                                     if keyed_by_division else None),
                # The column only appears in tables that have one, otherwise
                # every table on the site gains an empty column.
                "has_deductions": any(
                    _row_dict(r)["points_deducted"] for r in rows
                ),
            })
        return divisions_list

    def _coverage_note(self, year: int, tier: int, n_teams: int,
                       division_id: str | None = None) -> str:
        """
        Say so, on the table itself, when the table isn't the real one.

        A reader looking at 2002/03 League One sees clubs on 30 games in a
        46-game season and no explanation. The points and positions shown are
        what the fixtures we hold add up to, not what settled the division -
        which is exactly the sort of gap this site prints rather than hides.

        There are two ways a table can fail to be the real one, and until
        tier 5 was backfilled only the first existed. Fixtures can be
        missing, which the game count makes visible. Or every fixture can be
        present and one of them wrong, which nothing on the page betrays -
        the 1990/91 Alliance table has all 462 matches and still puts the
        wrong club top. Both are flagged the same way in the data; they need
        different sentences, and a table flagged for the second reason used
        to render with no note at all, because the fixture count came out
        even.
        """
        if "data_complete" not in self.standings_cols:
            return ""
        # Scoped to the division where the caller knows it: a merged tier
        # would compare one division's fixtures against a club count of
        # two, and flag both tables short when neither is.
        where, params = "tier = ?", (year, tier)
        if division_id is not None:
            where, params = "tier = ? AND division_id IS ?", (year, tier, division_id)
        row = self.conn.execute(
            "SELECT COALESCE(data_complete, 1) FROM standings"
            f" WHERE season_end_year = ? AND {where} LIMIT 1",
            params,
        ).fetchone()
        if not row or row[0]:
            return ""
        found = self.conn.execute(
            f"SELECT COUNT(*) FROM matches WHERE season_end_year = ? AND {where}",
            params,
        ).fetchone()[0]
        expected = aggregate.expected_match_count(n_teams)
        if found and expected and found < expected:
            return (
                f"Only {found} of this division's {expected} fixtures are in "
                f"the source data, so these totals and positions are not the "
                f"final table. They are excluded from records elsewhere on "
                f"the site."
            )
        reason = historical.TIER5_UNRELIABLE.get(year) if tier == 5 else None
        if reason:
            return (
                f"This table is complete but does not match the published "
                f"record: {reason}. The order shown is what the results in "
                f"the source add up to, not what settled the division, so it "
                f"is excluded from records elsewhere on the site."
            )
        if found >= expected:
            return (
                "This table does not match the published record, so the order "
                "shown is not the final one. It is excluded from records "
                "elsewhere on the site."
            )
        return ""

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
        the finding is a club with a Premier League season and a later
        tier-5 one. The ordering matters and is the whole claim: Luton Town
        also span both tiers, but their fifth-tier seasons came before their
        top-flight one, which is a rise, not a fall.

        Tier 1 is no longer the same thing as the Premier League. Backfilling
        to 1958/59 filled tier 1 with thirty-four seasons of the old First
        Division, and a bare "tier = 1" quietly turned this into a claim
        about the top flight in general - it started matching Leyton Orient,
        who were last in the first division in 1962/63. The sentence says
        Premier League, so the query has to say so too, which is what the
        season floor below is for.

        Two honesty notes, since this prints the word "only".

        Tier-5 coverage starts in 1979/80, so every club that left the
        Football League in the Premier League era is visible here - Halifax,
        Chester, Barnet, Exeter, Shrewsbury, York, Carlisle, Kidderminster
        and Cambridge United among them. None of them had played in the
        Premier League, so the answer is the same as it was when this note
        had to plead a 2005/06 window; it just no longer rests on one.

        And the recipe retires its own claim. If a second club ever qualifies
        the sentence becomes a count and the link moves to the page listing
        them all, so no deploy can leave a stale "only club" on the front
        page.
        """
        rows = self.conn.execute(
            """
            SELECT t.canonical_name AS name, s.club_id AS club_id,
                   t.current_tier   AS now_tier,
                   MIN(CASE WHEN s.tier = 1 AND s.season_end_year >= ?
                            THEN s.season_end_year END) AS first_top,
                   MIN(CASE WHEN s.tier = 5 THEN s.season_end_year END) AS first_fifth
            FROM standings s
            JOIN club_trajectory t ON t.club_id = s.club_id
            GROUP BY s.club_id
            HAVING first_top IS NOT NULL AND first_fifth IS NOT NULL
               AND first_fifth > first_top
            ORDER BY first_fifth, s.club_id
            """,
            (PREMIER_LEAGUE_FROM,),
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
            # Two points for a win before 1981/82 makes older totals
            # incomparable with later ones - see _standings_section.
            """
            SELECT club_name AS name, season_end_year AS year,
                   division_name AS division, points AS points,
                   position AS position
            FROM standings
            WHERE status = 'Relegated' AND played >= 30
              AND COALESCE(points_deducted, 0) = 0
              AND COALESCE(data_complete, 1) = 1
              AND season_end_year >= ?
            ORDER BY points DESC, club_name
            LIMIT 1
            """,
            (aggregate.THREE_POINTS_FROM,),
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
        # By division, not by tier: a tier can hold more than one, and a
        # page keyed on the tier would concatenate two league tables into
        # a single list of positions that each start at 1. Divisions with
        # no rows are skipped, so a registry entry awaiting data costs
        # nothing.
        # A committed database can predate the division_id column, and so
        # can a fixture. Such a database has one division per tier by
        # construction, so the tier addresses the division unambiguously -
        # the same degrade-rather-than-raise rule as trajectory_cols.
        keyed_by_division = "division_id" in self.standings_cols

        for division in divisions.DIVISIONS:
            slug, name, tier = division.division_id, division.name, division.tier
            if keyed_by_division:
                column, key = "division_id", slug
            elif divisions.sole_division(tier) is not None:
                column, key = "tier", tier
            else:
                continue
            season_years = [
                r[0] for r in self.conn.execute(
                    f"SELECT DISTINCT season_end_year FROM standings"
                    f" WHERE {column} = ? ORDER BY season_end_year DESC",
                    (key,),
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
                    f"""
                    SELECT * FROM standings
                    WHERE season_end_year = ? AND {column} = ?
                    ORDER BY position
                    """,
                    (year, key),
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
        # From the ladder, not a hardcoded list: a tier added to level.py
        # and forgotten here would be dropped from the bar while still
        # counting in its denominator, so every share would be wrong.
        # Empty buckets are skipped below, so this stays identical output.
        for key in ["outside" if b == level_mod.OUTSIDE else str(b)
                    for b in level_mod.BUCKET_LADDER]:
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
        depth = len(level_mod.BUCKET_LADDER) - 1        # the ladder minus "outside"
        depth_word = {5: "five", 6: "six", 7: "seven"}.get(depth, str(depth))
        window = (f"{seasons} seasons, {recorded} of them inside the top"
                  f" {depth_word} tiers"
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
        # Same false present tense as the risers table, on 189 club pages:
        # current_tier is the tier of the club's last recorded season, so
        # Wimbledon FC's page read "Current level: Tier 2" twenty-two years
        # after they were dissolved, and Margate's still reads tier 7 though
        # their data stops in 2018/19. The tagline already carries the span;
        # the label just has to stop claiming the present.
        playing = t["last_season_in_db"] == max(self.seasons)
        cards = [
            {"value": f"Tier {t['current_tier']}",
             "label": "Current level" if playing else "Level when last recorded"},
            {"value": t["current_tier_streak"],
             "label": "Seasons at this level" if playing else "Seasons in that spell"},
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
                catchment=self._club_catchment(club_id),
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
            has_club_table=self._has_club_table(),
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

    # Every column of the all-clubs table, in order: the key used to look
    # the value up, the header, the group it belongs to, and whether it
    # sorts as a number. Declared once so the header row, the cells and
    # the group spans cannot drift apart.
    CLUB_TABLE_COLUMNS = [
        ("name", "Club", "", False),
        ("season", "Season", "Where they finished", False),
        ("overall", "Overall", "Where they finished", True),
        ("division", "Division", "Where they finished", False),
        ("place", "Place", "Where they finished", True),
        ("current_tier", "Tier now", "Where they finished", True),
        ("natural_level", "Natural level", "Record", False),
        ("second_level", "Second level", "Record", False),
        ("level_share", "Share at it", "Record", True),
        ("trend", "Trend", "Record", False),
        ("level_gap", "Divisions off it", "Record", True),
        ("streak", "Seasons at level", "Record", True),
        ("range", "Tier range", "Record", False),
        ("seasons", "Seasons", "Record", True),
        ("seasons_inside", "Of them recorded", "Record", True),
        ("first_season", "First recorded", "Record", True),
        ("last_season", "Last recorded", "Record", True),
        ("gaps_ambiguous", "Gaps ambiguous", "Record", False),
        ("titles", "Titles", "Honours & sanctions", True),
        ("tier1", "Top-flight seasons", "Honours & sanctions", True),
        ("last_tier1", "Last top flight", "Honours & sanctions", True),
        ("promotions", "Promotions", "Honours & sanctions", True),
        ("relegations", "Relegations", "Honours & sanctions", True),
        ("yo_yo", "Yo-yo score", "Honours & sanctions", True),
        ("docked_points", "Points docked", "Honours & sanctions", True),
        ("docked_times", "Times docked", "Honours & sanctions", True),
        ("administrations", "Administrations", "Honours & sanctions", True),
        ("best", "Best finish", "All-time record", True),
        ("average", "Average finish", "All-time record", True),
        ("worst", "Worst finish", "All-time record", True),
        ("played", "Played", "All-time record", True),
        ("win_rate", "Win rate", "All-time record", True),
        ("goals_for", "Goals for", "All-time record", True),
        ("goals_against", "Goals against", "All-time record", True),
        ("goal_diff", "Goal difference", "All-time record", True),
        ("t1", "T1", "Seasons per tier", True),
        ("t2", "T2", "Seasons per tier", True),
        ("t3", "T3", "Seasons per tier", True),
        ("t4", "T4", "Seasons per tier", True),
        ("t5", "T5", "Seasons per tier", True),
        ("t6", "T6", "Seasons per tier", True),
        ("t7", "T7", "Seasons per tier", True),
        ("tout", "Outside", "Seasons per tier", True),
        ("founded", "Founded", "Club", True),
        ("nickname", "Nickname", "Club", False),
        ("origin_type", "How it began", "Club", False),
        ("rivals", "Rivals", "Club", True),
        ("stadium", "Ground", "Ground", False),
        ("capacity", "Capacity", "Ground", True),
        ("stadium_opened", "Opened", "Ground", True),
        ("ground_years", "Years there", "Ground", True),
        ("previous_grounds", "Former grounds", "Ground", True),
        ("ground_ownership", "Ground owned", "Ground", False),
        ("pitch_type", "Pitch", "Ground", False),
        ("ownership_model", "Ownership", "Ownership", False),
        ("owner", "Owner", "Ownership", False),
        ("owner_since", "Since", "Ownership", True),
        ("turnover", "Turnover", "accounts", True),
        ("wages", "Wages", "accounts", True),
        ("wage_ratio", "Wages \u00f7 rev", "accounts", True),
        ("profit", "Profit before tax", "accounts", True),
        ("net_debt", "Net debt", "accounts", True),
        ("rev_matchday", "Matchday", "accounts", True),
        ("rev_broadcast", "Broadcast", "accounts", True),
        ("rev_commercial", "Commercial", "accounts", True),
        ("catchment", "Catchment", "Catchment", True),
        ("catchment_ceiling", "At its ceiling", "Catchment", True),
        ("voronoi", "People nearest", "Catchment", True),
        ("contested", "Contested", "Catchment", True),
        ("catchment_income", "Household income", "Catchment", True),
        ("nearest", "Nearest club", "Catchment", False),
        ("nearest_tier", "Its tier", "Catchment", True),
        ("nearest_miles", "Miles", "Catchment", True),
        ("located", "Placed at", "Catchment", False),
    ]

    def _accounts_season(self) -> int | None:
        """
        The most recent season with filed accounts, which is not the most
        recent season played. Clubs file months after the season ends, so
        asking club_finances for the complete season returns nothing at
        all - which is how Arsenal first came out with five blank columns.
        """
        try:
            return self.conn.execute(
                "SELECT MAX(season_end_year) FROM club_finances"
                " WHERE disclosure = 'full'").fetchone()[0]
        except sqlite3.Error:
            return None

    def _club_table_data(self, season: int) -> dict:
        """
        Everything the all-clubs table needs, loaded once rather than once
        per club: 305 rows times six lookups is 1,800 queries for a page
        that can be built from six.
        """
        conn = self.conn
        trajectory = {r["club_id"]: r for r in conn.execute(
            "SELECT * FROM club_trajectory")}

        # A club's most recent season, and where it finished in it. The
        # offset that turns a place in a division into a place on the
        # ladder is per season, so it is computed once per season here
        # rather than per club.
        offsets: dict[tuple[int, int], int] = {}
        for year, tier, n in conn.execute(
                "SELECT season_end_year, tier, COUNT(*) FROM standings"
                " GROUP BY 1, 2"):
            offsets[(year, tier)] = n
        cumulative: dict[tuple[int, int], int] = {}
        for (year, tier) in offsets:
            cumulative[(year, tier)] = sum(
                n for (y, t), n in offsets.items() if y == year and t < tier)

        latest: dict[str, dict] = {}
        for row in conn.execute(
                "SELECT club_id, season_end_year, tier, position, tier_position,"
                " division_name FROM standings WHERE club_id IS NOT NULL"
                " ORDER BY season_end_year"):
            place = row[4] if row[4] is not None else row[3]
            latest[row[0]] = {
                "season": row[1], "tier": row[2], "place": row[3],
                "division": row[5],
                "overall": (place or 0) + cumulative.get((row[1], row[2]), 0),
            }

        finances = {}
        accounts_season = self._accounts_season()
        if accounts_season is not None:
            for row in conn.execute(
                    "SELECT club_id, turnover, staff_costs, profit_before_tax,"
                    " net_debt, revenue_matchday, revenue_broadcast,"
                    " revenue_commercial FROM club_finances"
                    " WHERE season_end_year = ? AND disclosure = 'full'",
                    (accounts_season,)):
                finances[row[0]] = row[1:]

        # A club's whole record in one pass, and its best, worst and
        # average place on the LADDER rather than in its own division -
        # fourth in the Championship and fourth in League Two are not the
        # same finish, and only the ladder says so.
        career: dict[str, dict] = {}
        for club_id, year, tier, place, status, played, won, gf, ga, docked in conn.execute(
                "SELECT club_id, season_end_year, tier,"
                " COALESCE(tier_position, position), status, played, won,"
                " gf, ga, COALESCE(points_deducted, 0) FROM standings"
                " WHERE club_id IS NOT NULL"):
            overall = (place or 0) + cumulative.get((year, tier), 0)
            entry = career.setdefault(club_id, {
                "seasons": 0, "titles": 0, "played": 0, "won": 0,
                "gf": 0, "ga": 0, "docked": 0, "places": [],
            })
            entry["seasons"] += 1
            entry["titles"] += 1 if status == "Champions" else 0
            entry["played"] += played or 0
            entry["won"] += won or 0
            entry["gf"] += gf or 0
            entry["ga"] += ga or 0
            entry["docked"] += docked or 0
            entry["places"].append(overall)

        # How many separate times, not how many points: a club docked ten
        # once and a club docked one point ten times are different stories.
        docked_times: dict[str, int] = {}
        try:
            for club_id, n in conn.execute(
                    "SELECT club_id, COUNT(*) FROM points_deductions"
                    " WHERE applied = 1 GROUP BY 1"):
                docked_times[club_id] = n
        except sqlite3.Error:
            pass

        catchment = {}
        if self._has_catchment():
            for row in conn.execute(
                    "SELECT club_id, catchment_pop_current,"
                    " catchment_pop_restored, catchment_income, contest_ratio,"
                    " nearest_rival_id, nearest_rival_miles, voronoi_pop,"
                    " nearest_rival_tier FROM club_catchment"):
                catchment[row[0]] = row[1:]

        tiers = dict(conn.execute(
            "SELECT club_id, current_tier FROM club_master"))

        grounds, names = {}, {}
        for club_id, name, stadium in conn.execute(
                "SELECT club_id, canonical_name, stadium_name FROM club_master"):
            names[club_id] = name
            if stadium:
                grounds[club_id] = stadium

        precision = {}
        if "location_precision" in self.master_cols:
            precision = {r[0]: r[1] for r in conn.execute(
                "SELECT club_id, location_precision FROM club_master")}

        return {"trajectory": trajectory, "latest": latest,
                "finances": finances, "accounts_season": accounts_season,
                "catchment": catchment, "grounds": grounds, "names": names,
                "career": career, "docked_times": docked_times,
                "precision": precision, "tiers": tiers}

    def _club_table_row(self, club_id: str, data: dict, season: int) -> list[dict]:
        """One club's cells, in CLUB_TABLE_COLUMNS order."""
        import json

        import level as level_mod

        def cell(text=None, sort=None, num=False, club_id=None):
            # sort defaults to the text, and a missing value carries no
            # sort key at all - the script puts those last in either
            # direction rather than treating a blank as a zero.
            return {"text": text, "sort": sort if sort is not None else text,
                    "num": num, "club_id": club_id}

        t = data["trajectory"].get(club_id)
        recent = data["latest"].get(club_id, {})
        facts = self.club_facts.get(club_id, {})
        fin = data["finances"].get(club_id)
        catch = data["catchment"].get(club_id)
        names = data.get("names", {})
        career = data["career"].get(club_id)

        def count_of(key):
            """A front-matter list's length, or None where nobody looked."""
            value = facts.get(key)
            return len(value) if isinstance(value, list) and value else None

        values = {
            "name": cell(t["canonical_name"] if t else club_id, club_id=club_id),
            "season": cell(season_label(recent["season"]) if recent else None,
                           sort=recent.get("season")),
            "overall": cell(recent.get("overall"), num=True),
            "division": cell(recent.get("division")),
            "place": cell(recent.get("place"), num=True),
            # Where they play NOW, which for a club last recorded in
            # 2018/19 is the only column that is not seven years old.
            "current_tier": cell(data["tiers"].get(club_id) or None, num=True),
        }

        if t:
            span = None
            if t["highest_tier"] is not None and t["lowest_tier"] is not None:
                span = (str(t["highest_tier"]) if t["highest_tier"] == t["lowest_tier"]
                        else f"{t['highest_tier']}\u2013{t['lowest_tier']}")
            values.update({
                "natural_level": cell(t["natural_level_label"]),
                "streak": cell(t["current_tier_streak"], num=True),
                "tier1": cell(t["seasons_in_tier1"], num=True),
                # Sorted by how wide the range is, not by the text: "1-5"
                # and "4-5" are not alphabetically meaningful.
                "range": cell(span, sort=(None if span is None else
                                          t["lowest_tier"] - t["highest_tier"])),
                "promotions": cell(t["total_promotions"], num=True),
                "relegations": cell(t["total_relegations"], num=True),
                "yo_yo": cell(f"{t['yo_yo_score']:.2f}"
                              if t["yo_yo_score"] is not None else None,
                              sort=t["yo_yo_score"], num=True),
                "first_season": cell(season_label(t["first_season_in_db"])
                                     if t["first_season_in_db"] else None,
                                     sort=t["first_season_in_db"], num=True),
                "last_season": cell(season_label(t["last_season_in_db"])
                                    if t["last_season_in_db"] else None,
                                    sort=t["last_season_in_db"], num=True),
                "seasons_inside": cell(t["natural_level_recorded"], num=True),
                "second_level": cell(
                    level_mod.bucket_name(t["natural_level_second_tier"],
                                          t["coverage_note"])
                    if t["natural_level_second_tier"] else None),
                "level_share": cell(
                    f"{t['natural_level_share']:.0%}"
                    if t["natural_level_share"] is not None else None,
                    sort=t["natural_level_share"], num=True),
                "trend": cell(t["natural_level_trend"]),
                # Positive is below its level, negative above, which is
                # how level.py computes it - the sign is the direction.
                "level_gap": cell(t["natural_level_gap"], num=True),
                "gaps_ambiguous": cell("yes" if t["coverage_note"] else None),
                "last_tier1": cell(season_label(t["last_tier1_season"])
                                   if t["last_tier1_season"] else None,
                                   sort=t["last_tier1_season"], num=True),
            })
            # A zero here is a fact - the club played no seasons at that
            # level - so unlike everywhere else on this row it is shown
            # and sorted rather than left blank.
            spread = json.loads(t["tier_distribution"] or "{}")
            for key, bucket in [("t1", "1"), ("t2", "2"), ("t3", "3"),
                                ("t4", "4"), ("t5", "5"), ("t6", "6"),
                                ("t7", "7"), ("tout", "outside")]:
                values[key] = cell(spread.get(bucket, 0), num=True)

        if career:
            places = career["places"]
            played, won = career["played"], career["won"]
            values.update({
                "seasons": cell(career["seasons"], num=True),
                "titles": cell(career["titles"], num=True),
                "best": cell(min(places), num=True),
                "worst": cell(max(places), num=True),
                "average": cell(f"{sum(places) / len(places):.1f}",
                                sort=sum(places) / len(places), num=True),
                "played": cell(f"{played:,}" if played else None,
                               sort=played or None, num=True),
                "win_rate": cell(f"{won / played:.0%}" if played else None,
                                 sort=(won / played) if played else None,
                                 num=True),
                "goals_for": cell(f"{career['gf']:,}" if career["gf"] else None,
                                  sort=career["gf"] or None, num=True),
                "goals_against": cell(f"{career['ga']:,}" if career["ga"]
                                      else None,
                                      sort=career["ga"] or None, num=True),
                "goal_diff": cell(f"{career['gf'] - career['ga']:+,}"
                                  if career["played"] else None,
                                  sort=career["gf"] - career["ga"], num=True),
                # Blank rather than nought: a club with no deduction has
                # nothing to say here, and a zero would sort it among the
                # clubs that were docked and got the points back.
                "docked_points": cell(career["docked"] or None, num=True),
                "docked_times": cell(data["docked_times"].get(club_id), num=True),
            })

        founded = facts.get("founded")
        opened = facts.get("stadium_opened")
        values.update({
            "founded": cell(founded, num=True),
            "nickname": cell(facts.get("nickname")),
            "stadium": cell(facts.get("stadium")
                            or data["grounds"].get(club_id)),
            "capacity": cell(f"{facts['capacity']:,}" if facts.get("capacity")
                             else None, sort=facts.get("capacity"), num=True),
            "ground_years": cell(season - opened if opened else None, num=True),
            "ground_ownership": cell(facts.get("stadium_ownership")),
            "ownership_model": cell(
                (facts.get("ownership_model") or "").replace("_", " ") or None),
            "owner": cell(facts.get("owner")),
            "owner_since": cell(facts.get("owner_since"), num=True),
            "origin_type": cell(
                (facts.get("origin_type") or "").replace("_", " ") or None),
            "rivals": cell(count_of("rivalries"), num=True),
            "previous_grounds": cell(count_of("previous_grounds"), num=True),
            "administrations": cell(count_of("administration"), num=True),
            "stadium_opened": cell(opened, num=True),
            "pitch_type": cell(
                (facts.get("pitch_type") or "").replace("_", " ") or None),
        })

        if fin:
            turnover, wages, profit, net_debt, matchday, broadcast, commercial = fin
            ratio = (wages / turnover) if turnover and wages else None
            values.update({
                "turnover": cell(_fmt_money(turnover) if turnover is not None
                                 else None, sort=turnover, num=True),
                "wages": cell(_fmt_money(wages) if wages is not None else None,
                              sort=wages, num=True),
                "wage_ratio": cell(f"{ratio:.0%}" if ratio is not None else None,
                                   sort=ratio, num=True),
                "profit": cell(_fmt_money(profit) if profit is not None else None,
                               sort=profit, num=True),
                "net_debt": cell(_fmt_money(net_debt) if net_debt is not None
                                 else None, sort=net_debt, num=True),
                "rev_matchday": cell(_fmt_money(matchday) if matchday is not None
                                     else None, sort=matchday, num=True),
                "rev_broadcast": cell(_fmt_money(broadcast)
                                      if broadcast is not None else None,
                                      sort=broadcast, num=True),
                "rev_commercial": cell(_fmt_money(commercial)
                                       if commercial is not None else None,
                                       sort=commercial, num=True),
            })

        if catch:
            (current, restored, income, contested, rival_id, miles, voronoi,
             rival_tier) = catch
            values.update({
                "catchment": cell(f"{current:,}" if current is not None else None,
                                  sort=current, num=True),
                "catchment_ceiling": cell(
                    f"{restored:,}" if restored is not None else None,
                    sort=restored, num=True),
                "catchment_income": cell(
                    f"\u00a3{income:,}" if income is not None else None,
                    sort=income, num=True),
                "contested": cell(f"{contested:.0%}" if contested is not None
                                  else None, sort=contested, num=True),
                "nearest": cell(names.get(rival_id, rival_id),
                                club_id=rival_id if rival_id in self.club_pages
                                else None),
                "nearest_miles": cell(f"{miles:.1f}" if miles is not None else None,
                                      sort=miles, num=True),
                # The denominator "contested" is a share of. Without it
                # the percentage cannot be checked against anything.
                "voronoi": cell(f"{voronoi:,}" if voronoi is not None else None,
                                sort=voronoi, num=True),
                "nearest_tier": cell(rival_tier or None, num=True),
            })

        # Whether the club's own coordinate is a surveyed ground or a town
        # centre, which every catchment figure on this row inherits.
        values["located"] = cell(data["precision"].get(club_id) or None)

        return [values.get(key, cell(num=num))
                for key, _label, _group, num in self.CLUB_TABLE_COLUMNS]

    def _has_club_table(self) -> bool:
        """
        Whether the all-clubs table gets built, which is the same question
        as whether there is a complete season to anchor it to. Asked in
        three places - the builder, the teams index and the insights index
        - because a link to a page that was not built is the one thing
        this site checks for on every build.
        """
        return self._complete_season() is not None

    def build_club_table(self) -> None:
        """
        Every club and everything known about it, in one sortable table.

        Two tables rather than one, because the rows would otherwise mean
        different things in the same sort. The first is the last complete
        season - _complete_season(), not the latest, which right now holds
        only three divisions and no Arsenal - where every club has a real
        position, division and place. The second is every other club on
        record, each showing where it last finished and when. Chester's
        2018/19 is not comparable with Arsenal's 2025/26 and one shared
        ordering would say it is.

        Runs after build_teams, which fills self.club_facts as it goes -
        the front-matter is read once for the club pages and reused here.
        """
        if not self._has_club_table():
            return
        season = self._complete_season()

        data = self._club_table_data(season)
        current = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT club_id FROM standings"
            " WHERE season_end_year = ? AND club_id IS NOT NULL", (season,))}

        # Ordered by where they finished, and by name for the clubs whose
        # last season is long past - the default has to mean something.
        def rows_for(club_ids, key):
            return [self._club_table_row(cid, data, season)
                    for cid in sorted(club_ids, key=key)]

        latest = data["latest"]
        now_rows = rows_for(
            [c for c in current if c in latest],
            lambda c: latest[c]["overall"])
        past = [c for c in data["trajectory"] if c not in current and c in latest]
        gone_rows = rows_for(
            past, lambda c: (-latest[c]["season"], latest[c]["overall"]))

        # The season columns say something different in the second table,
        # so its header does too.
        # The accounts group is named for the season it holds rather than
        # a year written into the column spec, which would be wrong the
        # moment another year of filings lands.
        accounts = data["accounts_season"]
        group_labels = {"accounts": (f"{season_label(accounts)} accounts"
                                     if accounts else "Accounts")}
        columns = [{"key": k, "label": label,
                    "group": group_labels.get(group, group), "num": num}
                   for k, label, group, num in self.CLUB_TABLE_COLUMNS]
        groups = []
        for column in columns:
            if groups and groups[-1]["label"] == column["group"]:
                groups[-1]["span"] += 1
            else:
                groups.append({"label": column["group"], "span": 1})

        self._write_club_csv(columns, now_rows + gone_rows)

        self.render(
            "club_table.html", self.out / "teams" / "table" / "index.html", 2,
            title="All clubs, all data",
            heading="All clubs, all data",
            intro=(
                f"Every club with a record here, and every column the data "
                f"supports. Click a heading to sort by it. A blank is "
                f"something not recorded rather than a zero, and blanks sort "
                f"last whichever way the column is ordered."
            ),
            columns=columns,
            groups=groups,
            tables=[
                {"heading": f"{season_label(season)}, the last complete season",
                 "note": f"{len(now_rows)} clubs, each with a final position "
                         f"in a season played to the end.",
                 "rows": now_rows},
                {"heading": "Every other club on record",
                 "note": f"{len(gone_rows)} clubs, showing where each last "
                         f"finished and when. These positions are from "
                         f"different seasons and are not comparable with each "
                         f"other.",
                 "rows": gone_rows},
            ],
        )

    def _write_club_csv(self, columns: list[dict], rows: list) -> None:
        """
        The same rows as a file, because at seventy-four columns the table
        cannot be the only way in. Anyone who wants a seventy-fifth field,
        or a chart, or a join against something else, should not have to
        scrape the page for it.

        The SORT value is written, not the displayed one: "£1.2m" is for
        reading and 1200000 is for computing with, and a CSV is for
        computing with. A blank stays blank rather than becoming a zero,
        the same rule the table sorts by.
        """
        import csv as csv_mod

        path = self.out / "teams" / "table" / "clubs.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv_mod.writer(fh)
            # club_id leads, and only here. The table links to it so it
            # does not need a column; a file does, because a display name
            # is not a key and anything joined against this will want the
            # permanent id rather than "Manchester United".
            writer.writerow(["club_id"] + [column["label"] for column in columns])
            for row in rows:
                writer.writerow(
                    [row[0]["club_id"] or ""]
                    + ["" if cell["sort"] is None else cell["sort"]
                       for cell in row]
                )
        logger.info("Wrote %s (%d clubs)", path.name, len(rows))

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

        # TIER_SLUGS holds only the tiers that ARE a division, so the sixth
        # and seventh drop out of this page by construction: a row here is
        # one division deep and those levels are two and four wide. That is
        # the right answer for a grid, but it should be said rather than
        # left for the reader to notice a pyramid that stops at five.
        parallel = sorted(
            {d.tier for d in divisions.DIVISIONS if d.tier not in TIER_SLUGS}
        )
        omitted = None
        if parallel:
            names = " and ".join(_ordinal(t) for t in parallel)
            omitted = (
                f"The {names} tiers are not here. Each is several divisions "
                "wide, and a grid with one row per level cannot say which of "
                "them a club was in. They are on the season pages and the "
                "club pages instead."
            )

        self.render(
            "matrix.html", self.out / "matrix" / "index.html", 1,
            title="The Matrix", season_columns=season_columns, rows=rows,
            omitted=omitted, main_class="wide",
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
            story("timeline", "Timeline", "Notable events in the pyramid"),
        ]
        # Gated on its prose like the other argued pages: the tile must not
        # offer a page that wasn't built.
        if (PROJECT_ROOT / "content" / "insights" / "the-pyramid.md").exists():
            stories.insert(0, story(
                "the-pyramid", "How English football is organised",
                "Eleven levels, and where the money runs out",
            ))
        if (PROJECT_ROOT / "content" / "insights" / "points-eras.md").exists():
            stories.append(story(
                "points-eras", "What a point is worth",
                "When winning away was worth more",
            ))
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

        # One tile for the three catchment metrics, same reasoning as the
        # financial group: they share a page and switch by chip. Absent
        # entirely until msoa_demographics.csv exists, because
        # _metric_landing_path returns None when nothing is plotted.
        catchment_path = next(
            (path for path in (
                self._metric_landing_path(key)
                for key, metric in METRICS.items() if metric["source"] == "catchment"
            ) if path),
            None,
        )
        if catchment_path:
            charts.append({
                "slug": "catchment",
                "name": "Catchment and competition",
                "sub": "How many people each club can draw on, and who else "
                       "wants them \u2014 with the method that produced it",
                "path": catchment_path,
            })

        # Not an insight and not a chart: the underlying data, for anyone
        # who would rather sort it themselves than read an argument about
        # it. Its own group so it is not mistaken for either.
        data_tables = [{
            "slug": "all-clubs",
            "name": "All clubs, all data",
            "sub": "Every column the data supports, sortable on any of them",
            "path": "teams/table/index.html",
        }] if self._has_club_table() else []

        groups = [g for g in (
            {"title": "Stories",
             "sub": "Arguments drawn from almost seventy years of league tables.",
             "entries": stories},
            {"title": "Interactive charts",
             "sub": "Pick a metric and a season, then read the pyramid.",
             "entries": charts},
            {"title": "The data itself",
             "sub": "Sort it yourself.",
             "entries": data_tables},
        ) if g["entries"]]

        self.render(
            "insights_index.html", self.out / "insights" / "index.html", 1,
            title="Insights", groups=groups, entries=stories + charts + data_tables,
        )
        self._insight_yo_yo()
        self._insight_natural_level()
        self._insight_fallen_giants()
        self._insight_records()
        self._insight_safe_thresholds()
        self._insight_timeline()
        self._insight_points_eras()
        self._insight_catchment()
        self._insight_pyramid()
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

    def _has_catchment(self) -> bool:
        """
        Whether the catchment model has actually run. The table is created
        on every pipeline pass but stays empty until msoa_demographics.csv
        exists (see docs/catchment-data.md), so existence is not enough -
        an empty table must read as "no data" and take the metric off the
        chip row entirely rather than rendering a blank chart.
        """
        if self._catchment_rows is None:
            try:
                self._catchment_rows = bool(self.conn.execute(
                    "SELECT 1 FROM club_catchment LIMIT 1").fetchone())
            except sqlite3.Error:
                self._catchment_rows = False
        return self._catchment_rows

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

    def _club_catchment(self, club_id: str) -> dict | None:
        """
        The catchment panel for one club's page, or None when the club has
        no row - so a club the model cannot see gets a shorter page rather
        than an empty shell, the same rule _club_finances follows.

        The headline is the club's catchment AT THE TIER IT IS IN NOW,
        because that is a fact about the present. The restored figure sits
        beside it only where the two differ, which is where the
        counterfactual is saying something: Arsenal are already at their
        ceiling and show one number, Leyton Orient show 325,076 and
        1,665,263.
        """
        # The same gate the charts use: the table is created on every
        # pipeline pass but stays empty without msoa_demographics.csv, and
        # a database can predate it entirely.
        if not self._has_catchment():
            return None
        row = self.conn.execute(
            "SELECT catchment_pop_current, catchment_pop_restored,"
            " catchment_income, contest_ratio, nearest_rival_id,"
            " nearest_rival_miles, voronoi_pop, model_version"
            " FROM club_catchment WHERE club_id = ?", (club_id,)
        ).fetchone()
        if row is None:
            return None
        (current, restored, income, contested, rival_id, rival_miles,
         voronoi, model_version) = row

        rival = None
        if rival_id:
            name = self.conn.execute(
                "SELECT canonical_name FROM club_master WHERE club_id = ?",
                (rival_id,)).fetchone()
            # A club placed at its local authority's centre is good to a
            # couple of miles, not to one - see _distance_phrase.
            approximate = False
            if "location_precision" in self.master_cols:
                precision = self.conn.execute(
                    "SELECT location_precision FROM club_master WHERE club_id = ?",
                    (rival_id,)).fetchone()
                approximate = bool(precision and precision[0] == "town")
            rival = {
                # Only where the club has a page. A club in the model with
                # no standings row is real and worth naming, and a link to
                # it would go nowhere.
                "club_id": rival_id if rival_id in self.club_pages else None,
                "name": name[0] if name else rival_id,
                "distance": _distance_phrase(rival_miles, approximate),
            }

        return {
            "population": f"{current:,}" if current is not None else None,
            # Only where it differs: an identical pair of numbers side by
            # side reads as a mistake rather than as a club at its peak.
            "restored": (f"{restored:,}"
                         if restored is not None and restored != current
                         else None),
            "income": f"\u00a3{income:,}" if income is not None else None,
            "contested": f"{contested:.0%}" if contested is not None else None,
            "voronoi": f"{voronoi:,}" if voronoi is not None else None,
            "rival": rival,
            "model_version": model_version,
        }

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

        if metric["source"] == "catchment":
            # Not season-scoped, like capacity: a catchment is one figure
            # per club, so the same value appears on every season's page
            # and only the plotted position moves.
            if not self._has_catchment():
                return {}
            names = dict(self.conn.execute(
                "SELECT club_id, canonical_name FROM club_master"))
            out: dict[str, dict] = {}
            for (cid, value, rival, miles, contest) in self.conn.execute(
                f"SELECT club_id, {metric['field']}, nearest_rival_id,"
                f" nearest_rival_miles, contest_ratio FROM club_catchment"
            ):
                if value is None:
                    continue
                plotted = float(value) * 100 if metric["field"] == "contest_ratio" \
                    else float(value)
                extra = {}
                if rival and miles is not None:
                    extra["rival"] = f"nearest club {names.get(rival, rival)}, {miles:.1f} miles"
                if metric["field"] != "contest_ratio" and contest is not None:
                    extra["contested"] = f"{contest * 100:.0f}% of its area contested"
                if metric["field"] == "catchment_income":
                    extra["caveat"] = "ONS small-area estimate, modelled not measured"
                out[cid] = {"value": plotted, "extra": extra}
            return out

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
        # See charts._ladder_position: a database without the column has
        # one division per tier, where position is the place in the level.
        ladder = ("COALESCE(s.tier_position, s.position)"
                  if "tier_position" in self.standings_cols else "s.position")
        rows = self.conn.execute(
            f"""
            SELECT s.club_id, s.tier, s.position,
                   {ladder} + (
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
                elif metric["source"] == "catchment":
                    # Of the clubs playing this season, not of every club
                    # the database holds - the same denominator the
                    # finance line uses, and the only one that means
                    # anything on a page plotting one season.
                    provenance = (
                        f"Modelled from ONS population and income for "
                        f"{len(points)} of {counts['in_season']} clubs in "
                        f"{season_label(year)} - not counted, and not a "
                        f"measurement."
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
                    # Three numbers nobody should read at face value get a
                    # link to what produced them, on every page that plots
                    # them rather than only on the index.
                    method_link=({"path": "insights/catchment/method/",
                                  "label": "How catchment is measured"}
                                 if metric["source"] == "catchment" else None),
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
        # club_trajectory.current_tier is the tier of a club's LAST recorded
        # season, not of this one, and 189 of the 305 clubs here have data
        # that has stopped - 116 of them the sixth and seventh tiers, which
        # end in 2018/19. Printing that under a column headed "Now" asserts
        # a present tense the data cannot support, and it was doing so:
        # WIMBLEDON FC, whose last season was 2002/03 and who were dissolved
        # in 2004, appeared under "The risers" as a club that now plays in
        # the top two divisions.
        #
        # The test is the one trajectory.py:155 already uses for is_active -
        # whether the club's last recorded season is the latest season. The
        # clubs it excludes are named in the note rather than dropped
        # silently, because "not playing any more" is the interesting half
        # of a page about clubs a long way from where they were.
        latest = max(self.seasons)

        def split(rows):
            playing = [r for r in rows if r["last_season_in_db"] == latest]
            dormant = [r for r in rows if r["last_season_in_db"] != latest]
            return playing, dormant

        fallen, fallen_dormant = split(self.conn.execute(
            """
            SELECT club_id, canonical_name, seasons_in_tier1, last_tier1_season,
                   current_tier, last_season_in_db
            FROM club_trajectory
            WHERE highest_tier = 1 AND current_tier >= 3
            ORDER BY current_tier DESC, last_tier1_season
            """
        ).fetchall())
        risers, risers_dormant = split(self.conn.execute(
            """
            SELECT * FROM (
                SELECT t.club_id, t.canonical_name, t.current_tier,
                       t.first_season_in_db, t.last_season_in_db,
                       (SELECT s.tier FROM standings s WHERE s.club_id = t.club_id
                        ORDER BY s.season_end_year LIMIT 1) AS first_tier
                FROM club_trajectory t
            ) WHERE first_tier >= 4 AND current_tier <= 2
            ORDER BY current_tier, first_tier DESC
            """
        ).fetchall())

        def with_dormant(note, dormant):
            if not dormant:
                return note
            named = ", ".join(
                f"{r['canonical_name']} (last recorded {season_label(r['last_season_in_db'])})"
                for r in dormant)
            return (f"{note} {named} would qualify on the record, but this "
                    f"column says where a club plays now and their data has "
                    f"stopped.")
        self.render(
            "insight_table.html",
            self.out / "insights" / "fallen-giants" / "index.html", 2,
            title="Fallen giants & risers",
            heading="Fallen giants & risers",
            intro="Clubs a long way from where they once were — in both directions.",
            sections=[
                {
                    "heading": "Fallen giants",
                    "note": with_dormant(
                        "Former top-flight clubs now in Tier 3 or below.",
                        fallen_dormant),
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
                    "note": with_dormant(
                        "Clubs that entered the database in Tier 4 or 5 and now "
                        "play in the top two divisions.", risers_dormant),
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
        points_comparable: bool = False,
    ) -> dict:
        """
        A "most/fewest X" style table. order/limit/where pick the rows -
        that's the actual selection, e.g. the 10 most extreme points
        totals across every division and era.

        points_comparable is for any table ranked on points. The Football
        League gave two points for a win until 1980/81 and three from
        1981/82, so a total from either side of that line does not mean the
        same thing, and ranking them together is not a like-for-like
        comparison - it reads QPR's 18 points in 1968/69 as a worse season
        than totals that were genuinely worse, when the same record under
        three points would have been 22. Those tables are restricted to the
        three-point era and say so. Tables ranked on goal difference need no
        such restriction.
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
        era = ""
        if points_comparable:
            era = f" AND s.season_end_year >= {aggregate.THREE_POINTS_FROM}"
            caveat = (f"From {aggregate.THREE_POINTS_FROM - 1}/"
                      f"{aggregate.THREE_POINTS_FROM % 100:02d} only, when three "
                      f"points for a win came in - earlier totals are not "
                      f"comparable.")
            note = f"{note} {caveat}".strip()
        rows = self.conn.execute(
            f"""
            SELECT {cols}
            FROM standings s
            WHERE ({where}){complete_only}{era}
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

    def _insight_catchment(self) -> None:
        """
        How the three catchment measures are arrived at, and what they are
        not.

        Every club page carries a catchment figure now, and a number like
        1,856,061 reads as a count when it is the output of a model with
        two judgement calls inside it. This is where those calls are
        named.

        The tables are read from the module and the database rather than
        written down, the same rule _insight_points_eras follows: the
        weights come out of catchment.TIER_ATTRACTIVENESS, so the page
        cannot describe a model the pipeline is not running.
        """
        import markdown as md
        from markupsafe import Markup

        source = PROJECT_ROOT / "content" / "insights" / "catchment.md"
        if not source.exists() or not self._has_catchment():
            return
        prose = content.load_theme(source)

        import catchment as catchment_mod
        import level as level_mod

        club_names = dict(self.conn.execute(
            "SELECT club_id, canonical_name FROM club_master"))

        # The pull weights, from the module rather than about it.
        weight_rows = []
        for tier, weight in sorted(catchment_mod.TIER_ATTRACTIVENESS.items()):
            if tier == 0:
                label = "No successor playing"
            else:
                label = level_mod.TIER_NAMES.get(tier, f"Tier {tier}")
            weight_rows.append([
                self._cell(label),
                self._cell(f"{weight:g}", num=True),
            ])

        sections = [{
            "heading": "How far each level draws from",
            "note": (f"Read from the same table the model computes with, so "
                     f"these are the weights actually applied. "
                     f"Distance decay \u03b2 = {catchment_mod.BETA:g}, no club "
                     f"closer than {catchment_mod.MIN_DISTANCE_MILES:g} miles "
                     f"to an area, model version "
                     f"{catchment_mod.MODEL_VERSION}."),
            "columns": ["Level", "Pull"],
            "rows": weight_rows,
        }]

        # The areas the model runs over. A database can hold a computed
        # club_catchment without the demographics it was computed from -
        # the table is dropped and rebuilt, the source CSV is not always
        # present - so the section is omitted rather than the page lost.
        try:
            msoas, people = self.conn.execute(
                "SELECT COUNT(*), SUM(population) FROM msoa_demographics").fetchone()
        except sqlite3.Error:
            msoas, people = None, None
        modelled = self.conn.execute(
            "SELECT COUNT(*) FROM club_catchment").fetchone()[0]
        total_clubs = self.conn.execute(
            "SELECT COUNT(*) FROM club_master").fetchone()[0]
        town = (self.conn.execute(
            "SELECT COUNT(*) FROM club_master"
            " WHERE location_precision = 'town'").fetchone()[0]
            if "location_precision" in self.master_cols else 0)
        counted = [
            [self._cell("Clubs with a figure"),
             self._cell(f"{modelled:,} of {total_clubs:,}", num=True)],
            [self._cell("Placed at a town centre, not a ground"),
             self._cell(f"{town:,}", num=True)],
        ]
        if msoas:
            counted = [
                [self._cell("Areas (MSOAs)"), self._cell(f"{msoas:,}", num=True)],
                [self._cell("People in them"), self._cell(f"{people:,}", num=True)],
            ] + counted
        sections.append({
            "heading": "What it is computed from",
            "note": "Population and income are ONS; the income layer is "
                    "modelled rather than measured, with intervals often "
                    "\u00b115%.",
            "columns": ["", "Count"],
            "rows": counted,
        })

        def _extremes(sql, fmt):
            return [[self._cell(club_names.get(cid, cid),
                                club_id=cid if cid in self.club_pages else None),
                     self._cell(fmt(value), num=True)]
                    for cid, value in self.conn.execute(sql)]

        top = _extremes(
            "SELECT club_id, catchment_pop_current FROM club_catchment"
            " ORDER BY catchment_pop_current DESC LIMIT 3", lambda v: f"{v:,}")
        contested = _extremes(
            "SELECT club_id, contest_ratio FROM club_catchment"
            " WHERE contest_ratio IS NOT NULL ORDER BY contest_ratio DESC LIMIT 3",
            lambda v: f"{v:.0%}")
        clear = _extremes(
            "SELECT club_id, contest_ratio FROM club_catchment"
            " WHERE contest_ratio IS NOT NULL ORDER BY contest_ratio LIMIT 3",
            lambda v: f"{v:.0%}")

        sections.append({
            "heading": "The largest catchments",
            "columns": ["Club", "People"],
            "rows": top,
        })
        sections.append({
            "heading": "Most and least contested",
            "note": "The share of the people nearest to a club that a bigger "
                    "neighbour takes. Both ends of the same measure.",
            "columns": ["Club", "Contested"],
            "rows": contested + clear,
        })

        gaps = [
            [self._cell(club_names.get(cid, cid),
                        club_id=cid if cid in self.club_pages else None),
             self._cell(f"{cur:,}", num=True),
             self._cell(f"{restored:,}", num=True)]
            for cid, cur, restored in self.conn.execute(
                "SELECT club_id, catchment_pop_current, catchment_pop_restored"
                " FROM club_catchment WHERE catchment_pop_current > 0"
                " ORDER BY catchment_pop_restored - catchment_pop_current DESC"
                " LIMIT 4")
        ]
        sections.append({
            "heading": "Where the counterfactual bites hardest",
            "note": "The four clubs whose catchment would change most on "
                    "returning to their highest recorded level, with every "
                    "other club left where it is. Clubs that no longer play "
                    "anywhere are excluded: their present figure is zero by "
                    "construction, which would top this table without "
                    "illustrating anything.",
            "columns": ["Club", "Now", "Restored to its ceiling"],
            "rows": gaps,
        })

        self.render(
            "insight_table.html",
            self.out / "insights" / "catchment" / "method" / "index.html", 3,
            title="How catchment is measured",
            heading="How catchment is measured",
            intro="Three numbers on every club page, none of them a count.",
            intro_html=Markup(md.markdown(prose)) if prose else None,
            sections=sections,
        )

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
            intro="The outer edges of almost seventy years of league tables.",
            sections=[
                self._standings_section("Most points in a season", "Full seasons only.",
                                   "s.points DESC, s.gd DESC",
                                   points_comparable=True),
                self._standings_section("Fewest points in a season", "The campaigns to forget.",
                                   "s.points ASC, s.gd ASC",
                                   points_comparable=True),
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
                    include_status=True, points_comparable=True,
                ),
                self._standings_section(
                    "Unlucky losers: the 46-game divisions", rest,
                    "s.points DESC, s.gd ASC", 10,
                    "s.played = 46 AND (s.status = 'Relegated' OR s.status = 'Play-off Relegated')",
                    include_status=True, points_comparable=True,
                ),
                self._standings_section(
                    "Lucky survivors: Premier League", top,
                    "s.points ASC, s.gd DESC", 10,
                    "s.played = 38 AND s.status = 'Stayed'",
                    include_status=True, points_comparable=True,
                ),
                self._standings_section(
                    "Lucky survivors: the 46-game divisions", rest,
                    "s.points ASC, s.gd DESC", 10,
                    "s.played = 46 AND s.status = 'Stayed'",
                    include_status=True, points_comparable=True,
                ),
            ],
        )


    def _insight_points_eras(self) -> None:
        """
        Why a points total only means something next to totals from its own
        era - and the season that proves it.

        Several tables on this site are quietly restricted to 1981/82
        onward, with a one-line caveat and nowhere explaining it. This is
        that explanation, and the Alliance Premier League's away-win
        experiment is the sharpest case available: 1984/85 has a different
        champion depending on which rule you count it under, so the point of
        the restriction stops being pedantry and becomes a name.

        Both tables are computed rather than written down. The rules table
        reads its figures from aggregate.points_rule(), so it cannot drift
        from what the pipeline actually applied, and the comparison is
        recomputed from the stored matches.
        """
        import markdown as md
        from markupsafe import Markup

        source = PROJECT_ROOT / "content" / "insights" / "points-eras.md"
        if not source.exists():
            return
        prose = content.load_theme(source)

        current = self.seasons[-1] if self.seasons else 2026
        spans = [
            ("Tiers 1-4", 1959, 1981), ("Tiers 1-4", 1982, current),
            ("Tier 5", 1980, 1981), ("Tier 5", 1982, 1983),
            ("Tier 5", 1984, 1986), ("Tier 5", 1987, current),
        ]
        rule_rows = []
        for label, first, last in spans:
            tier = 5 if label == "Tier 5" else 1
            home, away, draw = aggregate.points_rule(tier, last)
            span = (f"{season_label(first)}-{season_label(last)}"
                    if first != last else season_label(first))
            rule_rows.append([
                self._cell(label), self._cell(span),
                self._cell(home, num=True), self._cell(away, num=True),
                self._cell(draw, num=True),
            ])

        sections = [{
            "heading": "What a win was worth",
            "note": ("Read from the same table the pipeline computes with, so "
                     "these are the rules actually applied rather than a "
                     "description of them."),
            "columns": ["Divisions", "Seasons", "Home win", "Away win", "Draw"],
            "rows": rule_rows,
        }]

        comparison = self._away_win_comparison()
        if comparison:
            sections.append(comparison)

        self.render(
            "insight_table.html",
            self.out / "insights" / "points-eras" / "index.html", 2,
            title="What a point is worth",
            heading="What a point is worth",
            intro="Three seasons when winning away was worth more than winning at home.",
            intro_html=Markup(md.markdown(prose)) if prose else None,
            sections=sections,
        )

    def _away_win_comparison(self, year: int = 1985) -> dict | None:
        """
        The Alliance's 1984/85 table beside the same results counted three
        for a win, which is the version every later season uses.
        """
        try:
            rows = self.conn.execute(
                "SELECT home_name, away_name, fthg, ftag FROM matches"
                " WHERE season_end_year = ? AND tier = 5",
                (year,),
            ).fetchall()
        except sqlite3.Error as exc:
            # A database with no matches table, or one built before the
            # backfill, still gets the rules half of the page rather than
            # no page at all.
            logger.debug("Away-win comparison skipped: %s", exc)
            return None
        if not rows:
            return None

        clubs: dict[str, dict] = {}
        for home, away, hg, ag in rows:
            if hg is None or ag is None:
                continue
            for name in (home, away):
                clubs.setdefault(name, {"hw": 0, "aw": 0, "d": 0, "gf": 0, "ga": 0})
            clubs[home]["gf"] += hg; clubs[home]["ga"] += ag
            clubs[away]["gf"] += ag; clubs[away]["ga"] += hg
            if hg > ag:
                clubs[home]["hw"] += 1
            elif ag > hg:
                clubs[away]["aw"] += 1
            else:
                clubs[home]["d"] += 1; clubs[away]["d"] += 1

        def ranked(home_pts: int, away_pts: int) -> dict[str, tuple[int, int]]:
            table = sorted(
                ((v["hw"] * home_pts + v["aw"] * away_pts + v["d"],
                  v["gf"] - v["ga"], name) for name, v in clubs.items()),
                reverse=True,
            )
            return {name: (pos, pts) for pos, (pts, _gd, name) in enumerate(table, 1)}

        home_pts, away_pts, _draw = aggregate.points_rule(5, year)
        as_played = ranked(home_pts, away_pts)
        flat = ranked(3, 3)
        ids = dict(self.conn.execute(
            "SELECT club_name, club_id FROM standings"
            " WHERE season_end_year = ? AND tier = 5", (year,)))

        out = []
        for name, (pos, pts) in sorted(as_played.items(), key=lambda kv: kv[1][0])[:8]:
            flat_pos, flat_pts = flat[name]
            v = clubs[name]
            out.append([
                self._cell(name, ids.get(name)),
                self._cell(v["hw"], num=True), self._cell(v["aw"], num=True),
                self._cell(v["d"], num=True),
                self._cell(pts, num=True), self._cell(pos, num=True),
                self._cell(flat_pts, num=True), self._cell(flat_pos, num=True),
            ])
        return {
            "heading": f"{season_label(year)}: the same results, counted twice",
            "note": ("Left, the table as it was decided. Right, the same "
                     "matches under three points for a win. Wealdstone won "
                     "the title with the division's best away record; Bath "
                     "City had the best home record and finished fourth."),
            "columns": ["Club", "Home wins", "Away wins", "Draws",
                        "Points", "Pos", "If 3-1-0", "Pos"],
            "rows": out,
        }

    # The pyramid below tier 5, which this database does not hold. Counts
    # are the divisions' published composition for 2026/27 (the FA's club
    # allocations, 14 May 2026: 996 clubs across 48 divisions, 19 leagues
    # and six steps). Levels 9 and 10 carry no club total on purpose - the
    # FA regulations fix the number of divisions at sixteen and seventeen,
    # but divisions there run anywhere from 18 to 22 clubs and the FA
    # reprieves clubs each summer to fill them, so any total would be an
    # estimate dressed as a count.
    LOWER_PYRAMID = [
        (6, "National League North, National League South", 2, 48),
        (7, "Northern Premier, Southern (Central and South) and Isthmian "
            "leagues \u2014 premier divisions", 4, 88),
        (8, "The same four leagues, first divisions", 8, 176),
        (9, "Regional premier divisions", 16, None),
        (10, "Regional first divisions", 17, None),
        (11, "Regional feeder leagues, run by county FAs", None, None),
    ]

    def _insight_pyramid(self) -> None:
        """
        What the whole structure looks like, for a site that holds the top
        five levels of it.

        Two tables, and they answer different questions. The first is the
        shape: how far down it goes and how the single national divisions
        at the top give way to parallel regional ones. The second is
        whether the players are paid, which the accounts answer better than
        prose can - the wage bill falls by a factor of forty across four
        divisions that are all fully professional, which is the real answer
        to "professional or semi-professional": it is a gradient, and the
        gradient starts long before anyone stops being full-time.
        """
        import markdown as md
        from markupsafe import Markup

        source = PROJECT_ROOT / "content" / "insights" / "the-pyramid.md"
        if not source.exists():
            return
        prose = content.load_theme(source)

        sections = []
        levels = self._pyramid_levels()
        if levels:
            sections.append(levels)
        wages = self._pyramid_wages()
        if wages:
            sections.append(wages)

        self.render(
            "insight_table.html",
            self.out / "insights" / "the-pyramid" / "index.html", 2,
            title="How English football is organised",
            heading="How English football is organised",
            intro="Eleven levels, and the point where the money runs out.",
            intro_html=Markup(md.markdown(prose)) if prose else None,
            stats=self._pyramid_stats(),
            sections=sections,
        )

    def _complete_season(self) -> int | None:
        """
        The most recent season with a table for every tier this site holds.

        Not simply the latest season: that one is part-played, and when a
        download fails it can be short a division entirely, which would
        quietly drop a row from a table about how many divisions there are.
        """
        want = len(TIER_SLUGS)
        for year in reversed(self.seasons):
            n = self.conn.execute(
                "SELECT COUNT(DISTINCT tier) FROM standings"
                " WHERE season_end_year = ? AND status != 'In progress'",
                (year,),
            ).fetchone()[0]
            if n >= want:
                return year
        return None

    def _pyramid_levels(self) -> dict | None:
        """
        The levels this site holds, counted, followed by the ones it does
        not, stated. The two halves are independent on purpose: the lower
        pyramid is fixed reference data and should render even on a
        database too sparse to count the top of the table from.
        """
        rows = []
        year = self._complete_season()
        if year is not None:
            held = self.conn.execute(
                "SELECT tier, division_name, COUNT(*) FROM standings"
                " WHERE season_end_year = ? GROUP BY tier, division_name"
                " ORDER BY tier",
                (year,),
            ).fetchall()
            for tier, name, clubs in held:
                rows.append([
                    self._cell(tier, num=True), self._cell(name),
                    self._cell(1, num=True), self._cell(clubs, num=True),
                ])
        for level, name, divisions, clubs in self.LOWER_PYRAMID:
            rows.append([
                self._cell(level, num=True), self._cell(name),
                self._cell(divisions if divisions else "many", num=True),
                self._cell(clubs if clubs else "\u2014", num=True),
            ])
        if not rows:
            return None
        counted = (f"Levels 1-5 are counted from the {season_label(year)} "
                   f"tables held here, and below that " if year is not None
                   else "These are levels this site holds no tables for, so ")
        return {
            "heading": "The pyramid, level by level",
            "note": (f"{counted}the figures are the divisions' published "
                     f"composition. Levels 9 and 10 carry no club total "
                     f"because their divisions run anywhere from 18 to 22 "
                     f"clubs and the FA reprieves clubs each summer to fill "
                     f"them, so any total would be an estimate dressed as a "
                     f"count."),
            "columns": ["Level", "Competition", "Divisions", "Clubs"],
            "rows": rows,
        }

    def _pyramid_stats(self) -> list[dict]:
        """
        Counted where the database can count, stated where it cannot. The
        92 is this site's own; the 996 is the FA's allocation for 2026/27.
        """
        year = self._complete_season()
        cards = []
        if year is not None:
            pro = self.conn.execute(
                "SELECT COUNT(*) FROM standings"
                " WHERE season_end_year = ? AND tier <= 4", (year,),
            ).fetchone()[0]
            if pro:
                cards.append({"value": f"{pro}", "label": "fully professional clubs"})
        cards.append({"value": "996", "label": "clubs in the National League System"})
        cards.append({"value": "11", "label": "levels before the county leagues"})
        return cards

    def _pyramid_wages(self, year: int | None = None) -> dict | None:
        """
        The wage bill by division, which is the honest answer to whether
        players are paid. Denominators are shown because they matter: two
        League Two clubs filing a wage bill is not the League Two average,
        and a page that printed it as one would be doing the thing this
        site exists not to do.
        """
        if "club_finances" not in self._tables():
            return None
        if year is None:
            year = self.conn.execute(
                "SELECT MAX(f.season_end_year) FROM club_finances f"
                " WHERE f.staff_costs > 0"
            ).fetchone()[0]
        if year is None:
            return None
        rows = self.conn.execute(
            """
            SELECT s.tier, s.division_name,
                   COUNT(*) AS n,
                   AVG(f.staff_costs) AS avg_wages,
                   MIN(f.staff_costs) AS lo,
                   MAX(f.staff_costs) AS hi,
                   (SELECT COUNT(*) FROM standings s2
                     WHERE s2.season_end_year = s.season_end_year
                       AND s2.tier = s.tier) AS in_division
            FROM club_finances f
            JOIN standings s ON s.club_id = f.club_id
                            AND s.season_end_year = f.season_end_year
            WHERE f.staff_costs > 0 AND f.season_end_year = ?
            GROUP BY s.tier ORDER BY s.tier
            """,
            (year,),
        ).fetchall()
        if not rows:
            return None
        out = []
        for tier, name, n, avg_wages, lo, hi, in_division in rows:
            out.append([
                self._cell(name),
                self._cell(f"{n} of {in_division}", num=True),
                self._cell(_fmt_money(avg_wages), num=True),
                self._cell(f"{_fmt_money(lo)} - {_fmt_money(hi)}", num=True),
            ])
        return {
            "heading": f"What the wage bills say, {season_label(year)}",
            "note": ("Only clubs whose accounts this site holds, which is why "
                     "the second column is there - the lower the division, the "
                     "fewer clubs file accounts detailed enough to disclose a "
                     "wage bill at all, and below the Football League almost "
                     "none do."),
            "columns": ["Division", "Clubs with accounts",
                        "Average wage bill", "Range"],
            "rows": out,
        }

    def _tables(self) -> set:
        return {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}

    def _insight_timeline(self) -> None:
        events = [
            {"year": 1982, "title": "Three points for a win",
             "text": "The Football League raises a win from two points to three, to make attacking football pay. Every points total before this season is on a different scale from every total after it."},
            {"year": 1984, "title": "The Alliance pays more for winning away",
             "text": "For three seasons the Alliance Premier League awards two points for a home win and three for an away one — the only time an English national division has valued them differently. In 1984/85 it decides the title: Wealdstone win it on the division's best away record, and would have finished third under a flat three for a win."},
            {"year": 1987, "title": "The trapdoor opens",
             "text": "The Football League finally admits its champions: from 1986/87 the Alliance winner is promoted automatically instead of standing for election. Kidderminster in 1994 and Macclesfield in 1995 still win the title and are refused, on ground grading."},
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
        self.build_club_table()  # after build_teams: reuses self.club_facts
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
