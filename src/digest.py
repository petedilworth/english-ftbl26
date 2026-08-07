"""
Build and send the weekly fixture-preview digest.

Selects the most interesting upcoming fixtures (storyline scoring), writes
a mixed stats + narrative preview for each with an embedded two-club
position-history chart, lists the remaining fixtures compactly, and sends
the result via Resend.

Usage:
    python src/digest.py            # build and send (needs RESEND_* env)
    python src/digest.py --dry-run  # write digest_preview.html + charts locally
"""

import argparse
import datetime
import logging
import os
import sqlite3
import sys
from pathlib import Path

_SRC = Path(__file__).parent
sys.path.insert(0, str(_SRC))

import charts
import entities
import fixtures as fixtures_mod
import level as level_mod

PROJECT_ROOT = Path(__file__).parent.parent

logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────
FEATURED_COUNT = 6

# Clubs you always want featured when they play (club_id slugs).
# Can also be supplied as a comma-separated FOLLOWED_CLUBS env var.
FOLLOWED_CLUBS: list[str] = []

TIER_WEIGHT = {1: 5, 2: 4, 3: 3, 4: 2, 5: 2}

ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 21: "21st", 22: "22nd", 23: "23rd"}


def _ordinal(n: int) -> str:
    return ORDINALS.get(n, f"{n}th")


def _followed() -> set[str]:
    env = os.environ.get("FOLLOWED_CLUBS", "")
    return set(FOLLOWED_CLUBS) | {s.strip() for s in env.split(",") if s.strip()}


# ── Club context ────────────────────────────────────────────────────────────

# Natural level columns, added later than the rest of club_trajectory. The
# database file is committed to the repo, so a checkout can carry a table
# that predates them - the digest degrades to its older wording rather than
# raising OperationalError halfway through a scheduled run.
_LEVEL_COLUMNS = [
    "natural_level_tier", "natural_level_second_tier", "natural_level_kind",
    "natural_level_label", "natural_level_share", "natural_level_seasons",
    "recent_level_tier", "natural_level_trend", "natural_level_gap",
]


def _available(conn: sqlite3.Connection, table: str, wanted: list[str]) -> list[str]:
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    return [c for c in wanted if c in have]


def club_context(conn: sqlite3.Connection, club_id: str | None) -> dict | None:
    """Everything the narrative needs to know about one club."""
    if club_id is None:
        return None

    extra = _available(conn, "club_trajectory", _LEVEL_COLUMNS)
    row = conn.execute(
        f"""
        SELECT canonical_name, current_tier, current_tier_streak, highest_tier,
               lowest_tier, seasons_in_tier1, last_tier1_season,
               first_season_in_db, last_season_in_db,
               total_promotions, total_relegations, yo_yo_score
               {"".join(", " + c for c in extra)}
        FROM club_trajectory WHERE club_id = ?
        """,
        (club_id,),
    ).fetchone()
    if row is None:
        return None

    keys = ["name", "tier", "streak", "highest_tier", "lowest_tier",
            "seasons_in_tier1", "last_tier1_season", "first_season", "last_season",
            "promotions", "relegations", "yo_yo"] + extra
    ctx = dict(zip(keys, row))
    for missing in set(_LEVEL_COLUMNS) - set(extra):
        ctx[missing] = None
    ctx["club_id"] = club_id

    # For the "highest since" clause: the last time they were this far up
    # before the current season.
    ctx["highest_since"] = None
    if ctx["tier"] and ctx["last_season"]:
        found = conn.execute(
            "SELECT MAX(season_end_year) FROM standings"
            " WHERE club_id = ? AND tier <= ? AND season_end_year < ?",
            (club_id, ctx["tier"], ctx["last_season"]),
        ).fetchone()
        ctx["highest_since"] = found[0] if found else None

    ctx["recent_seasons"] = conn.execute(
        """
        SELECT season_end_year, division_name, position, points, status
        FROM standings WHERE club_id = ?
        ORDER BY season_end_year DESC LIMIT 5
        """,
        (club_id,),
    ).fetchall()

    latest = conn.execute(
        """
        SELECT position, points, played FROM standings
        WHERE club_id = ? ORDER BY season_end_year DESC LIMIT 1
        """,
        (club_id,),
    ).fetchone()
    ctx["position"], ctx["points"], ctx["played"] = latest if latest else (None, None, None)

    form_rows = conn.execute(
        """
        SELECT home_club_id, ftr FROM matches
        WHERE (home_club_id = ? OR away_club_id = ?)
          AND season_end_year = (SELECT MAX(season_end_year) FROM matches
                                 WHERE home_club_id = ? OR away_club_id = ?)
          AND match_date IS NOT NULL
        ORDER BY match_date DESC LIMIT 5
        """,
        (club_id, club_id, club_id, club_id),
    ).fetchall()
    form = []
    for home_id, ftr in form_rows:
        is_home = home_id == club_id
        if ftr == "D":
            form.append("D")
        elif (ftr == "H") == is_home:
            form.append("W")
        else:
            form.append("L")
    ctx["form"] = "".join(form)

    return ctx


def head_to_head(conn: sqlite3.Connection, a: str | None, b: str | None) -> dict | None:
    if a is None or b is None:
        return None
    row = conn.execute(
        """
        SELECT COUNT(*),
               SUM(CASE WHEN (home_club_id = :a AND ftr='H')
                          OR (away_club_id = :a AND ftr='A') THEN 1 ELSE 0 END),
               SUM(CASE WHEN (home_club_id = :b AND ftr='H')
                          OR (away_club_id = :b AND ftr='A') THEN 1 ELSE 0 END),
               SUM(CASE WHEN ftr='D' THEN 1 ELSE 0 END)
        FROM matches
        WHERE (home_club_id = :a AND away_club_id = :b)
           OR (home_club_id = :b AND away_club_id = :a)
        """,
        {"a": a, "b": b},
    ).fetchone()
    total, a_wins, b_wins, draws = (row[0], row[1] or 0, row[2] or 0, row[3] or 0)
    if not total:
        return None
    return {"total": total, "a_wins": a_wins, "b_wins": b_wins, "draws": draws}


# ── Storyline scoring ───────────────────────────────────────────────────────

def storyline_score(fixture: dict, home: dict | None, away: dict | None,
                    followed: set[str]) -> float:
    score = float(TIER_WEIGHT.get(fixture["tier"], 1))

    for ctx in (home, away):
        if ctx is None:
            continue
        score += ctx["yo_yo"]  # volatile histories are interesting
        gap = ctx.get("natural_level_gap")
        if gap is not None:
            # Distance from where the club belongs, in either direction.
            score += min(abs(gap), 3) * 2.0
            if gap < 0:
                score += 1.0  # climbing above your level is rarer than falling below it
            if ctx.get("natural_level_kind") == "yo-yo":
                score += 1.0
        elif ctx["highest_tier"] == 1 and fixture["tier"] >= 3:
            # Fallback for a thin record, or a database predating natural level
            score += 4  # fallen giant
        if ctx["recent_seasons"] and ctx["recent_seasons"][0][4] not in ("Stayed", None):
            score += 1  # promoted/relegated/champions last season

    if home and away and home["position"] and away["position"]:
        gap = abs(home["position"] - away["position"])
        if gap <= 3:
            score += 3  # near-neighbours in the table
        if home["position"] <= 3 and away["position"] <= 3:
            score += 3  # top-of-table clash

    if home and away:
        if {home["club_id"], away["club_id"]} & followed:
            score += 100

    return score


# ── Narrative ───────────────────────────────────────────────────────────────

def _level_sentence(ctx: dict) -> str | None:
    """
    What kind of club this is, and how far they currently sit from it.

    Composed from the structured fields rather than natural_level_label,
    which is display copy and doesn't decline into a sentence.
    """
    tier, kind = ctx.get("natural_level_tier"), ctx.get("natural_level_kind")
    if not tier or not kind or kind == "insufficient" or tier == level_mod.OUTSIDE:
        return None

    name = ctx["name"]
    here = level_mod.the(tier)

    if kind == "ever-present":
        clause = f"{name} have never played outside {here}"
    elif kind == "established":
        pct = round((ctx.get("natural_level_share") or 0) * 100)
        clause = (f"{name} belong in {here} — {pct}% of their "
                  f"{ctx.get('natural_level_seasons')} recorded seasons")
    elif kind == "yo-yo" and ctx.get("natural_level_second_tier"):
        a, b = sorted([tier, ctx["natural_level_second_tier"]])
        clause = f"{name} live between {level_mod.the(a)} and {level_mod.the(b)}"
    elif kind == "broad":
        clause = (f"{name}'s record runs the length of the pyramid, but its "
                  f"centre of gravity is {here}")
    else:
        clause = f"{name} are, on the balance of their record, a {level_mod.bucket_name(tier)} club"

    # The two directions are not mirror images. Falling below your level is
    # usually structural, so the deficit is the story; climbing above it is
    # usually a moment, so anchor it to when they were last this high
    # rather than implying the club is overachieving on borrowed time.
    gap = ctx.get("natural_level_gap")
    if gap and gap > 0:
        clause += f"; they are {gap} division{'s' if gap > 1 else ''} below that now"
    elif gap and gap < 0:
        up = abs(gap)
        divisions = f"{up} division{'s' if up > 1 else ''} above that"
        since, streak = ctx.get("highest_since"), ctx.get("streak") or 0
        if streak >= 3:
            # Settled at the higher level - the spell is the story, not the
            # single season, and "highest since last year" says nothing.
            clause += f"; they are {streak} seasons into a spell {divisions}"
        elif since and ctx["last_season"] - since >= 2:
            clause += f"; this season is their highest since {since}"
        elif since:
            clause += f"; they are {divisions} this season"
        else:
            clause += "; this season is the highest in their record"
    return clause


def _history_sentence(ctx: dict) -> str:
    name = ctx["name"]
    bits = []
    level_clause = _level_sentence(ctx)
    if level_clause:
        bits.append(level_clause)
    elif ctx["highest_tier"] == 1 and ctx["tier"] >= 3:
        last = ctx["last_tier1_season"]
        bits.append(
            f"{name} are a fallen giant — {ctx['seasons_in_tier1']} top-flight "
            f"season{'s' if ctx['seasons_in_tier1'] != 1 else ''}, the last in {last}, "
            f"now {ctx['tier'] - 1} divisions below"
        )
    elif ctx["yo_yo"] >= 0.25:
        promos, relgs = ctx["promotions"], ctx["relegations"]
        bits.append(
            f"{name} are a classic yo-yo club — {promos} "
            f"promotion{'s' if promos != 1 else ''} and {relgs} "
            f"relegation{'s' if relgs != 1 else ''} since {ctx['first_season']}"
        )
    elif ctx["streak"] >= 10:
        bits.append(
            f"{name} are furniture at this level — {ctx['streak']} consecutive "
            f"seasons and counting"
        )
    else:
        span = ctx["highest_tier"] != ctx["lowest_tier"]
        range_txt = (
            f"between tiers {ctx['highest_tier']} and {ctx['lowest_tier']}"
            if span else f"entirely at tier {ctx['highest_tier']}"
        )
        bits.append(
            f"{name} have spent their {ctx['last_season'] - ctx['first_season'] + 1} "
            f"recorded seasons {range_txt}"
        )
    if ctx["position"]:
        form = f", form {ctx['form']}" if ctx["form"] else ""
        bits.append(
            f"they sit {_ordinal(ctx['position'])} with {ctx['points']} points "
            f"from {ctx['played']} games{form}"
        )
    return "; ".join(bits) + "."


def narrative(fixture: dict, home: dict | None, away: dict | None,
              h2h: dict | None) -> str:
    division = fixture["division_name"]
    # "the Premier League" / "the Championship", but bare "League One" / "League Two"
    division_phrase = division if division.startswith("League") else f"the {division}"
    parts = []
    parts.append(
        f"{fixture['home_name']} host {fixture['away_name']} in "
        f"{division_phrase} on {fixture['date'].strftime('%A %d %B')}."
    )
    for ctx in (home, away):
        if ctx:
            parts.append(_history_sentence(ctx))
    if h2h and home and away:
        parts.append(
            f"They have met {h2h['total']} times in league play since 1993: "
            f"{home['name']} {h2h['a_wins']} wins, {away['name']} {h2h['b_wins']}, "
            f"{h2h['draws']} drawn."
        )
    return " ".join(parts)


# ── Rendering ───────────────────────────────────────────────────────────────

def _recent_table_html(ctx: dict) -> str:
    rows = "".join(
        f"<tr><td>{y}</td><td>{div}</td><td>{_ordinal(pos)}</td>"
        f"<td>{pts}</td><td>{st}</td></tr>"
        for y, div, pos, pts, st in ctx["recent_seasons"]
    )
    return (
        f"<table style='border-collapse:collapse;font-size:12px' cellpadding='4'>"
        f"<tr style='text-align:left'><th>Season</th><th>Division</th>"
        f"<th>Pos</th><th>Pts</th><th>Outcome</th></tr>{rows}</table>"
    )


def build_digest(conn: sqlite3.Connection, fixture_list: list[dict],
                 chart_dir: Path) -> tuple[str, str, str, list[tuple[Path, str]]]:
    """Returns (subject, html, text, inline_images)."""
    followed = _followed()

    enriched = []
    for f in fixture_list:
        home = club_context(conn, f["home_id"])
        away = club_context(conn, f["away_id"])
        h2h = head_to_head(conn, f["home_id"], f["away_id"])
        score = storyline_score(f, home, away, followed)
        enriched.append((score, f, home, away, h2h))
    enriched.sort(key=lambda e: -e[0])

    featured = enriched[:FEATURED_COUNT]
    rest = enriched[FEATURED_COUNT:]

    week_of = min(f["date"] for f in fixture_list).strftime("%d %B %Y")
    subject = f"Football week ahead — {len(fixture_list)} fixtures from {week_of}"

    html_parts = [
        "<div style='font-family:Georgia,serif;max-width:680px;margin:auto;color:#1a1a1a'>",
        f"<h1 style='font-size:22px'>The Week Ahead</h1>",
        f"<p style='color:#555'>{len(fixture_list)} fixtures across "
        f"{len({f['tier'] for f in fixture_list})} divisions, week of {week_of}.</p>",
        "<h2 style='font-size:18px;border-bottom:2px solid #1a1a1a'>Featured matches</h2>",
    ]
    text_parts = [f"THE WEEK AHEAD — week of {week_of}", ""]
    images: list[tuple[Path, str]] = []

    for i, (score, f, home, away, h2h) in enumerate(featured):
        story = narrative(f, home, away, h2h)
        html_parts.append(
            f"<h3 style='font-size:15px;margin-bottom:2px'>{f['home_name']} v "
            f"{f['away_name']} <span style='color:#888;font-weight:normal'>"
            f"({f['division_name']}, {f['date'].strftime('%a %d %b')})</span></h3>"
        )
        html_parts.append(f"<p style='font-size:14px;line-height:1.5'>{story}</p>")

        cid = f"chart-{i}"
        chart_path = charts.fixture_chart(
            conn, f["home_id"], f["away_id"],
            f["home_name"], f["away_name"],
            chart_dir / f"{cid}.png",
        )
        if chart_path:
            html_parts.append(
                f"<img src='cid:{cid}' alt='Position history' "
                f"style='max-width:100%;margin:4px 0'/>"
            )
            images.append((chart_path, cid))

        tables = [
            _recent_table_html(ctx) for ctx in (home, away) if ctx and ctx["recent_seasons"]
        ]
        if tables:
            cells = "".join(f"<td style='vertical-align:top;padding-right:18px'>{t}</td>"
                            for t in tables)
            html_parts.append(f"<table><tr>{cells}</tr></table>")

        text_parts += [f"* {f['home_name']} v {f['away_name']} "
                       f"({f['division_name']}, {f['date']:%a %d %b})", f"  {story}", ""]

    if rest:
        html_parts.append(
            "<h2 style='font-size:18px;border-bottom:2px solid #1a1a1a'>Also this week</h2>")
        text_parts.append("ALSO THIS WEEK")
        current_div = None
        for score, f, home, away, h2h in sorted(rest, key=lambda e: (e[1]["tier"], e[1]["date"])):
            if f["division_name"] != current_div:
                current_div = f["division_name"]
                html_parts.append(f"<h4 style='margin:10px 0 2px'>{current_div}</h4>")
                text_parts.append(f"  [{current_div}]")
            html_parts.append(
                f"<div style='font-size:13px'>{f['date']:%a %d} — "
                f"{f['home_name']} v {f['away_name']}</div>"
            )
            text_parts.append(f"    {f['date']:%a %d}: {f['home_name']} v {f['away_name']}")

    html_parts.append(
        "<p style='color:#999;font-size:11px;margin-top:24px'>Generated from "
        "football-data.co.uk results, Tiers 1–5, 1993/94–present.</p></div>"
    )
    return subject, "".join(html_parts), "\n".join(text_parts), images


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly fixture digest")
    parser.add_argument("--dry-run", action="store_true",
                        help="write digest_preview.html instead of sending")
    parser.add_argument("--db-path", type=Path,
                        default=PROJECT_ROOT / "data" / "db" / "england.db")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    conn = sqlite3.connect(args.db_path)
    resolver = entities.build_resolver(conn)

    fixture_list = fixtures_mod.fetch_fixtures(resolver)
    if not fixture_list:
        logger.info("No fixtures in the coming week — nothing to send.")
        return 0

    chart_dir = PROJECT_ROOT / "preview" / "charts"
    subject, html, text, images = build_digest(conn, fixture_list, chart_dir)

    if args.dry_run:
        out = PROJECT_ROOT / "preview" / "digest_preview.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        # inline cid: references won't render from disk; swap to relative paths
        preview_html = html
        for path, cid in images:
            preview_html = preview_html.replace(f"cid:{cid}", f"charts/{path.name}")
        out.write_text(preview_html, encoding="utf-8")
        logger.info("Dry run: wrote %s (%d featured charts)", out, len(images))
        return 0

    import notify
    notify.send_email(subject, html, text, images)
    _archive_digest(html, images)
    return 0


def _archive_digest(html: str, images: list[tuple[Path, str]]) -> None:
    """
    Save a browsable copy of the sent digest under content/digests/<date>/
    so the website's archive page can publish it. Committed back to the
    repo by the weekly workflow.
    """
    import datetime
    import shutil

    archive_dir = PROJECT_ROOT / "content" / "digests" / datetime.date.today().isoformat()
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_html = html
    for path, cid in images:
        shutil.copy(path, archive_dir / path.name)
        archived_html = archived_html.replace(f"cid:{cid}", path.name)
    (archive_dir / "index.html").write_text(archived_html, encoding="utf-8")
    logger.info("Archived digest to %s", archive_dir)


if __name__ == "__main__":
    raise SystemExit(main())
