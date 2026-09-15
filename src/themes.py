"""
The theme pages: an intro and one sorted table each, nothing else.

Membership comes from the database where the database knows -
points_deductions drives the deductions page and seeds the administration
page - and from the club stories' front-matter where only they do:
phoenix clubs, fan ownership, ground grading. Administration is the
union, because the table only records administrations that carried a
deduction and the pre-2004 ones (Barnsley 2002, Birmingham 1992) did not.

A theme with fewer than MIN_THEME_CLUBS members is not built. Three
ground-grading cases is a footnote, not a page.

Every row builder returns (columns, rows, dimension): rows are lists of
cells, a cell is {"text", "href"?, "num"?}, and dimension is the sort the
reader is told about ("by points docked").
"""

import logging
import sqlite3
from collections import defaultdict

import content

logger = logging.getLogger(__name__)

MIN_THEME_CLUBS = 8

DB_THEMES = ("points-deductions", "administration")


def season_label(year: int | None) -> str:
    return "" if not year else f"{year - 1}/{year % 100:02d}"


def ordinal(n: int | None) -> str:
    if n is None:
        return ""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


# ── Membership ─────────────────────────────────────────────────────────────

def db_membership(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Theme members the database can vouch for."""
    if not _has_table(conn, "points_deductions"):
        return {}
    members: dict[str, set[str]] = {"points-deductions": set(), "administration": set()}
    for club_id, category in conn.execute(
            "SELECT club_id, category FROM points_deductions WHERE club_id IS NOT NULL"):
        members["points-deductions"].add(club_id)
        if category == "administration":
            members["administration"].add(club_id)
    return members


def membership(conn: sqlite3.Connection,
               story_themes: dict[str, list[str]]) -> dict[str, set[str]]:
    """
    slug -> club_ids. Deductions: the database only - a story that lists
    a deduction the table lacks is a gap in points_deductions.csv, and is
    logged as one. Administration: the union. Everything else: the stories.
    """
    by: dict[str, set[str]] = defaultdict(set)
    for club_id, slugs in story_themes.items():
        for slug in slugs:
            if slug in content.THEMES:
                by[slug].add(club_id)
    from_db = db_membership(conn)
    story_only = by.get("points-deductions", set()) - from_db.get("points-deductions", set())
    if from_db:
        for club_id in sorted(story_only):
            logger.warning("%s lists a points deduction its story alone knows about;"
                           " add it to points_deductions.csv", club_id)
        by["points-deductions"] = set(from_db["points-deductions"])
        by["administration"] |= from_db["administration"]
    return dict(by)


def published(members: dict[str, set[str]]) -> set[str]:
    return {slug for slug, ids in members.items() if len(ids) >= MIN_THEME_CLUBS}


# ── Standings helpers ──────────────────────────────────────────────────────

def _standing(conn: sqlite3.Connection, club_id: str, season: int) -> dict | None:
    cols = _columns(conn, "standings")
    deducted = "points_deducted" if "points_deducted" in cols else "0"
    division = "division_id" if "division_id" in cols else "NULL"
    row = conn.execute(
        f"SELECT division_name, position, points, {deducted}, gd, gf, status, tier, {division}"
        " FROM standings WHERE club_id = ? AND season_end_year = ?",
        (club_id, season)).fetchone()
    if row is None:
        return None
    keys = ["division", "position", "points", "deducted", "gd", "gf", "status", "tier", "division_id"]
    return dict(zip(keys, row))


def _would_have_finished(conn: sqlite3.Connection, club_id: str, season: int,
                         standing: dict) -> int | None:
    """Position on points before the deduction, everyone else as they were."""
    if not standing or not standing.get("deducted"):
        return None
    cols = _columns(conn, "standings")
    deducted = "points_deducted" if "points_deducted" in cols else "0"
    if standing.get("division_id"):
        where, arg = "division_id = ?", standing["division_id"]
    else:
        where, arg = "tier = ?", standing["tier"]
    rows = conn.execute(
        f"SELECT club_id, points + COALESCE({deducted}, 0), gd, gf FROM standings"
        f" WHERE season_end_year = ? AND {where}", (season, arg)).fetchall()
    # Only this club is restored; the others keep the points they ended on.
    restored = []
    for cid, full, gd, gf in rows:
        pts = full if cid == club_id else conn.execute(
            "SELECT points FROM standings WHERE club_id = ? AND season_end_year = ?",
            (cid, season)).fetchone()[0]
        restored.append((cid, pts or 0, gd or 0, gf or 0))
    restored.sort(key=lambda r: (-r[1], -r[2], -r[3]))
    for n, (cid, *_rest) in enumerate(restored, start=1):
        if cid == club_id:
            return n
    return None


def _level(standing: dict | None, with_status: bool = False) -> str:
    if not standing:
        return "—"
    text = f"{standing['division']}, {ordinal(standing['position'])}"
    if with_status and standing.get("status") and standing["status"] not in ("Stayed", "In progress", None):
        text += f" ({standing['status'].lower()})"
    return text


def _club_cell(club_id: str, names: dict[str, str]) -> dict:
    return {"text": names.get(club_id, club_id), "href": f"team/{club_id}/index.html"}


def _cell(text, num: bool = False) -> dict:
    return {"text": "" if text is None else str(text), "num": num}


# ── Row builders ───────────────────────────────────────────────────────────

def deduction_rows(conn, members, facts_by_club, names):
    if not _has_table(conn, "points_deductions"):
        return (["Club", "Season", "Division", "Points", "Reason", "Finished", "Without it"],
                [], "by points docked")
    story_reasons = {}
    for club_id, facts in facts_by_club.items():
        for e in facts.get("points_deductions") or []:
            if isinstance(e, dict) and e.get("season_end_year") and e.get("reason"):
                story_reasons[(club_id, int(e["season_end_year"]))] = str(e["reason"]).strip()
    rows = []
    for club_id, season, points, applied, reason in conn.execute(
            "SELECT club_id, season_end_year, points, applied, reason FROM points_deductions"
            " WHERE club_id IS NOT NULL ORDER BY points DESC, season_end_year DESC, club_id"):
        if club_id not in members:
            continue
        st = _standing(conn, club_id, season)
        text = story_reasons.get((club_id, season)) or reason or ""
        if text and len(story_reasons.get((club_id, season), "")) < len(reason or ""):
            text = reason
        if not applied:
            text = (text + " " if text else "") + "(suspended)"
        would = _would_have_finished(conn, club_id, season, st) if applied else None
        rows.append([
            _club_cell(club_id, names), _cell(season_label(season)),
            _cell(st["division"] if st else ""), _cell(points, num=True), _cell(text),
            _cell(ordinal(st["position"]) if st else "", num=True),
            _cell(ordinal(would) if would and would != st["position"] else "—", num=True),
        ])
    return (["Club", "Season", "Division", "Points", "Reason", "Finished", "Without it"],
            rows, "by points docked")


def administration_rows(conn, members, facts_by_club, names):
    entries: dict[tuple[str, int], dict] = {}
    if _has_table(conn, "points_deductions"):
        for club_id, season, points, note in conn.execute(
                "SELECT club_id, season_end_year, points, note FROM points_deductions"
                " WHERE category = 'administration' AND club_id IS NOT NULL"):
            entries[(club_id, season)] = {"points": points, "note": note or ""}
    for club_id, facts in facts_by_club.items():
        for e in facts.get("administration") or []:
            if not isinstance(e, dict):
                continue
            season = content.to_season_end_year(content.first_year(e.get("year")),
                                                "calendar", e.get("month"))
            if not season:
                continue
            entry = entries.setdefault((club_id, season), {"points": e.get("points_deducted") or 0,
                                                            "note": ""})
            if e.get("note"):
                entry["note"] = str(e["note"]).strip()
    rows = []
    for (club_id, season), entry in sorted(entries.items(), key=lambda kv: (-kv[0][1], kv[0][0])):
        if club_id not in members:
            continue
        rows.append([
            _cell(season_label(season)), _club_cell(club_id, names),
            _cell(entry["points"] or "—", num=True),
            _cell(_level(_standing(conn, club_id, season - 1))),
            _cell(_level(_standing(conn, club_id, season), with_status=True)),
            _cell(_level(_standing(conn, club_id, season + 2))),
            _cell(entry["note"]),
        ])
    return (["Season", "Club", "Points", "The season before", "That season", "Two seasons on", "Note"],
            rows, "most recent first")


def phoenix_rows(conn, members, facts_by_club, names):
    rows = []
    for club_id in members:
        facts = facts_by_club.get(club_id, {})
        founded = content.first_year(facts.get("founded"))
        first = conn.execute(
            "SELECT season_end_year, division_name FROM standings WHERE club_id = ?"
            " AND season_end_year > ? ORDER BY season_end_year LIMIT 1",
            (club_id, founded or 0)).fetchone()
        best = conn.execute(
            "SELECT tier, MIN(season_end_year), division_name FROM standings WHERE club_id = ?"
            " AND season_end_year > ? AND tier = (SELECT MIN(tier) FROM standings"
            " WHERE club_id = ? AND season_end_year > ?)",
            (club_id, founded or 0, club_id, founded or 0)).fetchone()
        reached = best[1] if best and best[1] else None
        rows.append([
            _club_cell(club_id, names), _cell(facts.get("phoenix_of", "")),
            _cell(content.first_year(facts.get("predecessor_folded")) or "", num=True),
            _cell(founded or "", num=True),
            _cell(f"{season_label(first[0])}, {first[1]}" if first else "not yet recorded"),
            _cell(f"{best[2]}, {season_label(reached)}" if best and best[0] else "—"),
            _cell((reached - founded) if reached and founded else "", num=True),
        ])
    rows.sort(key=lambda r: (-(int(r[3]["text"]) if r[3]["text"] else 0), r[0]["text"]))
    return (["Club", "Predecessor", "Folded", "Refounded", "First recorded season",
             "Highest level since", "Seasons to get there"],
            rows, "most recent first")


def fan_owned_spells(facts: dict) -> list[dict]:
    spells = []
    for e in facts.get("fan_owned") or []:
        if isinstance(e, dict) and content.first_year(e.get("from")):
            spells.append({"trust": e.get("trust") or "Supporters' trust",
                           "from": content.first_year(e.get("from")),
                           "to": content.first_year(e.get("to"))})
    if facts.get("ownership_model") == "fan_trust" and content.first_year(facts.get("owner_since")):
        spells.append({"trust": facts.get("owner") or "Supporters' trust",
                       "from": content.first_year(facts.get("owner_since")), "to": None})
    return spells


def fan_owned_rows(conn, members, facts_by_club, names):
    rows = []
    for club_id in members:
        # An open spell ends at the club's own latest season on file, which
        # for a club below the recorded divisions is not the current one.
        latest = conn.execute("SELECT MAX(season_end_year) FROM standings WHERE club_id = ?",
                              (club_id,)).fetchone()[0]
        for spell in fan_owned_spells(facts_by_club.get(club_id, {})):
            start = _standing(conn, club_id, spell["from"] + 1)
            end_season = spell["to"] if spell["to"] else latest
            end = _standing(conn, club_id, end_season) if end_season else None
            rows.append([
                _club_cell(club_id, names), _cell(spell["trust"]),
                _cell(spell["from"], num=True), _cell(spell["to"] or "now", num=True),
                _cell(_level(start)), _cell(_level(end)),
            ])
    rows.sort(key=lambda r: (int(r[2]["text"]), r[0]["text"]))
    return (["Club", "Trust", "From", "To", "Level when they took over", "Level now, or when it ended"],
            rows, "oldest first")


def ground_grading_rows(conn, members, facts_by_club, names):
    rows = []
    for club_id in members:
        for e in facts_by_club.get(club_id, {}).get("ground_grading_denial") or []:
            if not isinstance(e, dict) or not e.get("season_end_year"):
                continue
            season = int(e["season_end_year"])
            st = _standing(conn, club_id, season)
            rows.append([
                _club_cell(club_id, names), _cell(season_label(season)),
                _cell(_level(st, with_status=True)), _cell(str(e.get("note") or "").strip()),
            ])
    rows.sort(key=lambda r: (r[1]["text"], r[0]["text"]))
    return ["Club", "Season", "Finished", "What happened"], rows, "oldest first"


BUILDERS = {
    "points-deductions": deduction_rows,
    "administration": administration_rows,
    "phoenix": phoenix_rows,
    "fan-owned": fan_owned_rows,
    "ground-grading": ground_grading_rows,
}


def rows_for(slug, conn, members, facts_by_club, names):
    builder = BUILDERS.get(slug)
    if builder is None:
        return [], [], ""
    return builder(conn, members, facts_by_club, names)
