"""
The suppression rule from docs/voice.md: human events force a straight
tone. This reads content/straight-dates.yml and answers one question -
should this edition, mentioning these clubs on this date, be plain?

The file starts empty. Nothing here is wired into the neutral templates
yet; the function exists so the path is in place before the first joke.
"""

import datetime
from pathlib import Path

import yaml

from editions import config


def load(path: Path = config.STRAIGHT_DATES) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [e for e in data if isinstance(e, dict)]


def straight(date: datetime.date, club_ids: set[str],
             entries: list[dict] | None = None) -> bool:
    """
    True if any entry applies. A dated entry applies on its anniversary
    (month and day) to its clubs, or to everyone if it names none; an
    undated entry applies to its clubs on every date.
    """
    for e in (load() if entries is None else entries):
        clubs = set(e.get("clubs") or [])
        when = e.get("date")
        if isinstance(when, str):
            when = datetime.date.fromisoformat(when)
        date_matches = when is None or (when.month, when.day) == (date.month, date.day)
        club_matches = not clubs or bool(clubs & club_ids)
        if date_matches and club_matches:
            return True
    return False
