"""
Render a two-club "overall league position over time" chart as a PNG,
in the style of smcgivern/historical-league-positions: one continuous
y-axis across all tiers, position 1 at the top.
"""

import logging
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)

COLORS = ("#2166ac", "#e08214")


def overall_positions(conn: sqlite3.Connection, club_id: str) -> list[tuple[int, int]]:
    """
    A club's overall position per season: league position plus the number
    of clubs in higher tiers that season (league sizes varied over time,
    so the offset is computed per season rather than assumed).
    """
    rows = conn.execute(
        """
        SELECT s.season_end_year,
               s.position + (
                   SELECT COUNT(*) FROM standings s2
                   WHERE s2.season_end_year = s.season_end_year
                     AND s2.tier < s.tier
               ) AS overall_pos
        FROM standings s
        WHERE s.club_id = ?
        ORDER BY s.season_end_year
        """,
        (club_id,),
    ).fetchall()
    return [(int(season), int(pos)) for season, pos in rows]


def fixture_chart(
    conn: sqlite3.Connection,
    home_id: str | None,
    away_id: str | None,
    home_label: str,
    away_label: str,
    out_path: Path,
) -> Path | None:
    """
    Save an overlaid position-history chart for the two clubs in a fixture.
    Returns the path, or None if neither club has any history.
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
            series.append((label, color, points))

    if not series:
        return None

    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=110)
    for label, color, points in series:
        years = [p[0] for p in points]
        positions = [p[1] for p in points]
        ax.plot(years, positions, color=color, linewidth=1.6, label=label)

    ax.invert_yaxis()
    ax.set_ylabel("Overall league position")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=9, framealpha=0.9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path
