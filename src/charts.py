"""
Render league position charts as PNGs, in the style of
smcgivern/historical-league-positions: one continuous y-axis across all
tiers, position 1 at the top.

Styling matches the site's CSS custom properties (static/style.css) so
this chart and the interactive SVG trajectory chart (static/chart.js)
read as the same design: --muted for axis text, --line for gridlines,
white background, no tick marks, unboxed legend, round line joins.
"""

import logging
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)

COLORS = ("#2166ac", "#e08214")

MUTED = "#6b7683"
LINE = "#e4e8ec"
INK = "#17202a"
UP = "#1a7f3c"
DOWN = "#b3261e"

# Mirrors static/style.css's --tier-1..--tier-5, for the same reason MUTED/
# LINE/INK do: matplotlib can't read CSS custom properties, so this is kept
# in sync by hand.
TIER_COLORS = {
    1: "#5e35b1",
    2: "#1e88e5",
    3: "#43a047",
    4: "#fb8c00",
    5: "#e53935",
}


def tier_floors(conn: sqlite3.Connection) -> tuple[dict[int, list[int]], int]:
    """
    For each season in the standings table, the cumulative club count at
    each tier boundary (e.g. [20, 44, 68, 92] for a 20+24+24+24-club
    pyramid that season), omitting the final boundary since there's no
    tier below it to separate. Also returns the largest overall position
    seen across all seasons, for y-axis scaling.

    Shared by the interactive SVG chart and this module's PNG charts so
    tier boundaries are only computed once.
    """
    years = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT season_end_year FROM standings ORDER BY season_end_year"
        )
    ]
    floors_by_year: dict[int, list[int]] = {}
    max_pos = 0
    for year in years:
        counts = conn.execute(
            "SELECT tier, COUNT(*) FROM standings WHERE season_end_year = ?"
            " GROUP BY tier ORDER BY tier",
            (year,),
        ).fetchall()
        floors, running = [], 0
        for _tier, n in counts:
            running += n
            floors.append(running)
        max_pos = max(max_pos, running)
        floors_by_year[year] = floors[:-1]
    return floors_by_year, max_pos


def overall_positions(
    conn: sqlite3.Connection, club_id: str
) -> list[tuple[int, int, str | None]]:
    """
    A club's overall position per season: league position plus the number
    of clubs in higher tiers that season (league sizes varied over time,
    so the offset is computed per season rather than assumed). Each point
    also carries an event marker, "promoted" or "relegated" or None,
    derived from the (already-reconciled) standings.status column.

    A Tier 1 "Champions" is a title, not a promotion - there's no tier
    above the Premier League to move up into - so it does not count as
    a "promoted" event. This mirrors the same tier > 1 condition used to
    fix club_trajectory's promotion count.
    """
    rows = conn.execute(
        """
        SELECT s.season_end_year,
               s.position + (
                   SELECT COUNT(*) FROM standings s2
                   WHERE s2.season_end_year = s.season_end_year
                     AND s2.tier < s.tier
               ) AS overall_pos,
               CASE
                   WHEN s.status IN ('Champions', 'Promoted', 'Play-off Promoted')
                        AND s.tier > 1 THEN 'promoted'
                   WHEN s.status IN ('Relegated', 'Play-off Relegated') THEN 'relegated'
                   ELSE NULL
               END AS event
        FROM standings s
        WHERE s.club_id = ?
        ORDER BY s.season_end_year
        """,
        (club_id,),
    ).fetchall()
    return [(int(season), int(pos), event) for season, pos, event in rows]


def point_tiers(conn: sqlite3.Connection, club_id: str) -> dict[int, int]:
    """{season_end_year: tier} for one club - used to colour fixture_chart's
    line by tier without changing overall_positions()'s (year, pos, event)
    shape, which the SVG chart's JSON payload also depends on."""
    return {
        int(year): int(tier)
        for year, tier in conn.execute(
            "SELECT season_end_year, tier FROM standings WHERE club_id = ?",
            (club_id,),
        )
    }


def _tier_segments(
    points: list[tuple[int, int, str | None]], tiers: dict[int, int]
) -> list[tuple[int | None, list[tuple[int, int]]]]:
    """
    Group a club's (year, pos, event) points into runs that share both the
    same tier and consecutive years - the same gap rule used elsewhere
    (trajectory._compute_tier_streaks(), movement.py), so a genuine gap in
    the standings isn't silently bridged by a straight line. Each run after
    the first repeats the previous run's final point as its own first
    point, so the drawn line stays visually continuous across a tier
    change instead of showing a break.

    Returns [(tier, [(year, pos), ...]), ...].
    """
    runs: list[tuple[int | None, list[tuple[int, int]]]] = []
    current: list[tuple[int, int]] = []
    prev_year = prev_tier = None

    for year, pos, _event in points:
        tier = tiers.get(year)
        contiguous = prev_year is not None and year - prev_year == 1
        if current and not contiguous:
            # A genuine gap in the standings - close the run without
            # bridging, so no line is drawn across seasons we don't have.
            runs.append((prev_tier, current))
            current = []
        elif current and tier != prev_tier:
            # A tier change with no gap - bridge so the line stays
            # continuous, at the cost of the transition segment being
            # coloured for the tier being entered rather than the one left.
            runs.append((prev_tier, current))
            current = [current[-1]]
        current.append((year, pos))
        prev_year, prev_tier = year, tier

    if current:
        runs.append((prev_tier, current))
    return runs


def fixture_chart(
    conn: sqlite3.Connection,
    home_id: str | None,
    away_id: str | None,
    home_label: str,
    away_label: str,
    out_path: Path,
    show_tier_lines: bool = False,
    show_events: bool = False,
    color_by_tier: bool = False,
) -> Path | None:
    """
    Save an overlaid position-history chart for the two clubs in a fixture.
    Returns the path, or None if neither club has any history.

    show_tier_lines/show_events default off so the digest email's two-club
    comparison chart is unaffected; team pages opt in to both.

    color_by_tier also defaults off and is team-page-only: it replaces each
    club's single solid-colour line with per-tier-coloured segments, which
    only makes sense for a single club's own history - two clubs sharing a
    tier at the same time would render identically and the comparison
    would stop working.
    """
    series = []
    for club_id, label, color in (
        (home_id, home_label, COLORS[0]),
        (away_id, away_label, COLORS[1]),
    ):
        if club_id is None:
            continue
        points = overall_positions(conn, club_id)
        if points:
            series.append((club_id, label, color, points))

    if not series:
        return None

    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=110)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    if show_tier_lines:
        all_years = [p[0] for _, _, _, points in series for p in points]
        floors_by_year, _ = tier_floors(conn)
        min_year, max_year = min(all_years), max(all_years)
        relevant_years = sorted(
            y for y in floors_by_year if min_year <= y <= max_year
        )
        boundary_count = max(
            (len(floors_by_year[y]) for y in relevant_years), default=0
        )
        for b in range(boundary_count):
            ys = [
                floors_by_year[y][b] + 0.5 if b < len(floors_by_year[y]) else float("nan")
                for y in relevant_years
            ]
            ax.plot(
                relevant_years, ys,
                color=LINE, linewidth=1, drawstyle="steps-post", zorder=0,
            )

    tiers_seen: set[int] = set()
    for club_id, label, color, points in series:
        if color_by_tier:
            tiers = point_tiers(conn, club_id)
            for tier, run in _tier_segments(points, tiers):
                run_years = [p[0] for p in run]
                run_positions = [p[1] for p in run]
                ax.plot(
                    run_years, run_positions,
                    color=TIER_COLORS.get(tier, MUTED), linewidth=1.6,
                    solid_joinstyle="round", solid_capstyle="round", zorder=2,
                )
                if tier is not None:
                    tiers_seen.add(tier)
        else:
            years = [p[0] for p in points]
            positions = [p[1] for p in points]
            ax.plot(
                years, positions, color=color, linewidth=1.6, label=label,
                solid_joinstyle="round", solid_capstyle="round", zorder=2,
            )
        if show_events:
            promoted = [(p[0], p[1]) for p in points if p[2] == "promoted"]
            relegated = [(p[0], p[1]) for p in points if p[2] == "relegated"]
            if promoted:
                px, py = zip(*promoted)
                ax.scatter(px, py, color=UP, s=28, zorder=3,
                          edgecolors="white", linewidths=0.6)
            if relegated:
                rx, ry = zip(*relegated)
                ax.scatter(rx, ry, color=DOWN, s=28, zorder=3,
                          edgecolors="white", linewidths=0.6)

    ax.invert_yaxis()
    ax.set_ylabel("Overall league position", color=MUTED, fontsize=10)
    ax.tick_params(colors=MUTED, length=0, labelsize=9)
    if color_by_tier:
        # A per-club legend entry would be meaningless once the line itself
        # is multiple colours - show which tiers those colours mean instead.
        import level as level_mod
        from matplotlib.lines import Line2D

        handles = [
            Line2D([0], [0], color=TIER_COLORS.get(t, MUTED), linewidth=1.6,
                   label=level_mod.TIER_NAMES.get(t, f"Tier {t}"))
            for t in sorted(tiers_seen)
        ]
        if handles:
            ax.legend(handles=handles, loc="best", fontsize=9, frameon=False,
                      labelcolor=INK)
    else:
        ax.legend(loc="best", fontsize=9, frameon=False, labelcolor=INK)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines["left"].set_color(LINE)
    ax.spines["bottom"].set_color(LINE)
    fig.tight_layout()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path
