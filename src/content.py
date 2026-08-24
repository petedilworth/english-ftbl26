"""
Parse club narrative files (content/<club_id>.md) into structured facts
and named prose sections.

Each file is optional YAML front-matter between --- fences, followed by
markdown whose ## headings map to a fixed set of sections. Everything is
optional: a club with no file, no front-matter, or only some sections
still renders cleanly - the site just shows less.

Themes are derived from the facts rather than tagged by hand, so the
club listed on the "fan-owned" page is always the club whose
ownership_model actually says so.
"""

import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Prose sections, rendered in this order. Keys are the lowercase heading
# text authors write after "## "; values are the display headings.
SECTIONS = {
    "origins": "Origins",
    "trajectory": "Trajectory",
    "ownership & finance": "Ownership & Finance",
    "infrastructure & environment": "Infrastructure & Environment",
}

# Accept a few forgiving spellings for each canonical section, so a
# missed ampersand doesn't silently drop a section to the bottom.
_ALIASES = {
    "origin": "origins",
    "ownership and finance": "ownership & finance",
    "ownership": "ownership & finance",
    "finance": "ownership & finance",
    "infrastructure and environment": "infrastructure & environment",
    "infrastructure": "infrastructure & environment",
}

THEMES = {
    "phoenix": "Phoenix clubs",
    "fan-owned": "Fan-owned clubs",
    "administration": "Clubs that entered administration",
    "points-deductions": "Clubs docked points",
    "exiled": "Clubs exiled from their town",
    "ground-grading": "Promotion denied on ground grading",
}

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_H2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def parse_front_matter(text: str) -> tuple[dict, str]:
    """
    Split leading YAML front-matter from the markdown body.
    Returns (facts, body). Malformed YAML is logged and skipped rather
    than raising - one bad file shouldn't fail the whole site build.
    """
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text

    try:
        facts = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        logger.warning("Skipping malformed front-matter: %s", exc)
        return {}, text[match.end():]

    if not isinstance(facts, dict):
        logger.warning("Front-matter is not a mapping - ignoring")
        facts = {}
    return facts, text[match.end():]


def split_sections(body: str) -> tuple[dict[str, str], str]:
    """
    Split markdown on ## headings into {canonical_key: markdown}.
    Returns (sections, extra) where extra is any prose that didn't match
    a canonical heading - kept rather than dropped, so nothing an author
    writes disappears silently.
    """
    matches = list(_H2.finditer(body))
    if not matches:
        text = body.strip()
        return {}, text

    sections: dict[str, str] = {}
    extra_parts = []

    preamble = body[: matches[0].start()].strip()
    if preamble:
        extra_parts.append(preamble)

    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        heading = m.group(1).strip().lower()
        key = _ALIASES.get(heading, heading)
        content = body[m.end():end].strip()
        if not content:
            continue
        if key in SECTIONS:
            sections[key] = content
        else:
            extra_parts.append(f"## {m.group(1).strip()}\n\n{content}")

    return sections, "\n\n".join(extra_parts).strip()


def derive_themes(facts: dict) -> list[str]:
    """
    Work out which theme pages a club belongs on, from its facts.
    Any manual `themes:` entries are merged in for angles the structured
    fields can't express.
    """
    themes = set()

    if facts.get("phoenix_of"):
        themes.add("phoenix")
    if facts.get("ownership_model") == "fan_trust":
        themes.add("fan-owned")
    if facts.get("administration"):
        themes.add("administration")
    if facts.get("points_deductions"):
        themes.add("points-deductions")
    if facts.get("exile"):
        themes.add("exiled")
    if facts.get("ground_grading_denial"):
        themes.add("ground-grading")

    manual = facts.get("themes") or []
    if isinstance(manual, str):
        manual = [manual]
    themes.update(str(t).strip() for t in manual if str(t).strip())

    return sorted(themes)


# ── Theme events and narrative ──────────────────────────────────────────
#
# Both are derived from the same facts that put the club on the theme in the
# first place, so a club needs no extra authoring to get a dated dot on the
# theme chart and a passage explaining why it's there. `theme_notes:` in the
# front-matter overrides the derived prose where something richer is wanted.
#
# Two traps the derivation has to absorb:
#  - Calendar years and season-end years both appear in the schema.
#    administration.year is a calendar year; points_deductions.season_end_year
#    is a season-end year. Coventry has both for the same 2013/14 saga.
#  - Range fields (exile.seasons, previous_grounds.years) are free text and
#    use an en-dash, so they can't be split on "-".

_YEAR = re.compile(r"(1[89]\d{2}|20\d{2})")


def first_year(value) -> int | None:
    """
    First four-digit year in a value, whatever shape it arrives in.
    Handles the free-text ranges ("1997-1999", en-dash and all) that the
    exile and previous_grounds fields use.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1800 <= value <= 2100 else None
    match = _YEAR.search(str(value))
    return int(match.group(1)) if match else None


def to_season_end_year(year: int | None, kind: str, month=None) -> int | None:
    """
    Put a year on the standings axis, which is keyed by season-end year.

    Seasons run August-May, so a calendar year N straddles two of them and
    the month decides which: August-December of N belongs to the season
    ending N+1, January-July of N to the season ending N.

    Without a month there is nothing to decide on, and the fallback assumes
    the second half of the year - right for a club founded or an owner
    arriving over the summer, which is what the undated fields describe.
    It is wrong for insolvency, which is overwhelmingly a mid-season event:
    of the administrations recorded here, most fall between January and May,
    so they belong to the season ending in their own calendar year. Pass the
    month whenever the record gives one.
    """
    if year is None:
        return None
    month = _month_number(month)
    if month:
        return year + 1 if month >= 8 else year
    return year + 1 if kind == "calendar" else year


_MONTH_LABELS = dict(enumerate(
    ("January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"), 1))

_MONTH_NAMES = {name.lower(): number for number, name in _MONTH_LABELS.items()}


def _month_number(value) -> int | None:
    """
    A month as 1-12, from an integer or a name ("February", "feb"). Anything
    else - None, a typo, a number out of range - reads as "not recorded", so
    a bad value falls back to the undated behaviour rather than throwing.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 12 else None
    text = str(value).strip().lower()
    if text.isdigit():
        number = int(text)
        return number if 1 <= number <= 12 else None
    for name, number in _MONTH_NAMES.items():
        if name.startswith(text) and len(text) >= 3:
            return number
    return None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def theme_events(slug: str, facts: dict) -> list[dict]:
    """
    Dated events explaining why a club sits on a theme, as
    [{season_end_year, label, text}] sorted oldest first.
    """
    facts = facts or {}
    events: list[dict] = []

    def add(year, kind, label, text, month=None):
        season = to_season_end_year(first_year(year), kind, month)
        if season:
            events.append({"season_end_year": season, "label": label, "text": text})

    if slug == "administration":
        for e in facts.get("administration") or []:
            if not isinstance(e, dict):
                continue
            pts = e.get("points_deducted")
            month = _month_number(e.get("month"))
            when = f"{_MONTH_LABELS[month]} {e.get('year')}" if month else f"{e.get('year')}"
            text = f"Entered administration in {when}"
            if pts:
                text += f", and was docked {_plural(int(pts), 'point')}"
            text += "."
            if e.get("note"):
                text += f" {e['note']}."
            add(e.get("year"), "calendar", "Administration", text, e.get("month"))

    elif slug == "points-deductions":
        for e in facts.get("points_deductions") or []:
            if not isinstance(e, dict) or not e.get("points"):
                continue
            text = f"Docked {_plural(int(e['points']), 'point')}"
            if e.get("season_end_year"):
                text += f" in {_season_label(int(e['season_end_year']))}"
            text += "."
            if e.get("reason"):
                text += f" {e['reason']}."
            add(e.get("season_end_year"), "season", "Points deduction", text)

    elif slug == "exiled":
        for e in facts.get("exile") or []:
            if not isinstance(e, dict) or not e.get("venue"):
                continue
            text = f"Played home games at {e['venue']}"
            if e.get("seasons"):
                text += f", {e['seasons']}"
            if e.get("distance_miles"):
                text += f" — about {e['distance_miles']} miles from home"
            text += "."
            add(e.get("seasons"), "calendar", "Exile begins", text)

    elif slug == "ground-grading":
        for e in facts.get("ground_grading_denial") or []:
            if not isinstance(e, dict):
                continue
            note = e.get("note") or "Promotion denied on ground grading"
            add(e.get("season_end_year"), "season", "Ground grading", f"{note}.")

    elif slug == "phoenix":
        folded = facts.get("predecessor_folded")
        if folded and facts.get("phoenix_of"):
            add(folded, "calendar", "Predecessor folded",
                f"{facts['phoenix_of']} ceased to exist in {folded}.")
        if facts.get("founded"):
            text = f"Founded in {facts['founded']}"
            if facts.get("phoenix_of"):
                text += f", succeeding {facts['phoenix_of']}"
            text += "."
            add(facts.get("founded"), "calendar", "Club founded", text)

    elif slug == "fan-owned":
        if facts.get("owner_since"):
            owner = facts.get("owner") or "The supporters' trust"
            add(facts["owner_since"], "calendar", "Fans take control",
                f"{owner} took control in {facts['owner_since']}.")

    events.sort(key=lambda e: e["season_end_year"])
    return events


def theme_narrative(slug: str, facts: dict) -> str:
    """
    A passage explaining why this club is on this theme. Derived from the
    facts, unless the club's front-matter overrides it via
    `theme_notes: {<slug>: "..."}`.
    """
    facts = facts or {}

    notes = facts.get("theme_notes")
    if isinstance(notes, dict):
        override = notes.get(slug)
        if override and str(override).strip():
            return str(override).strip()

    events = theme_events(slug, facts)
    if events:
        return " ".join(e["text"] for e in events)
    return ""


def load_theme(path: Path) -> str:
    """
    A theme's introductory prose (content/themes/<slug>.md). Returns "" when
    there's no file, so a theme without one simply shows no intro.
    """
    if not path.exists():
        return ""
    _facts, body = parse_front_matter(path.read_text(encoding="utf-8"))
    return body.strip()


def _season_label(year: int) -> str:
    """Season-end year to display label, e.g. 2014 -> 2013/14."""
    return f"{year - 1}/{year % 100:02d}"


def load_club(path: Path) -> dict | None:
    """
    Read one club narrative file. Returns None if it doesn't exist, so
    callers can treat "no story yet" as the normal case it is.
    """
    if not path.exists():
        return None

    text = path.read_text(encoding="utf-8")
    facts, body = parse_front_matter(text)
    sections, extra = split_sections(body)

    return {
        "facts": facts,
        "sections": sections,
        "extra": extra,
        "themes": derive_themes(facts),
        "has_prose": bool(sections or extra),
    }
