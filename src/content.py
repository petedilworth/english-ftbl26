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
    "council-ground": "Council-owned grounds",
    "multi-club": "Part of a multi-club group",
    "stadium-moves": "Clubs that moved ground",
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
    if facts.get("stadium_ownership") == "council":
        themes.add("council-ground")
    if facts.get("multi_club_group"):
        themes.add("multi-club")
    if facts.get("previous_grounds"):
        themes.add("stadium-moves")

    manual = facts.get("themes") or []
    if isinstance(manual, str):
        manual = [manual]
    themes.update(str(t).strip() for t in manual if str(t).strip())

    return sorted(themes)


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
