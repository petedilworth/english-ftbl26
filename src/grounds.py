"""
Who owns the ground: the researched record in content/grounds.yml, one
entry per club, each with its sources.

    club           the club, or the group that owns the club - the ground
                   goes with the club in a sale
    owner_company  the owner personally, or a company of the owner's that
                   is not the club - sell the club and the ground stays
                   behind, usually after a sale-and-leaseback
    council        the local authority; the club leases or licenses it
    landlord       anyone else: a former owner, a property company, a
                   trust, a school
    other_club     a tenant of another football or rugby club
    unknown        researched and not established

The file is merged into each club's facts when the club file is read
(content.load_club), so the facts panel, the theme pages and the value
model all see the same answer. It overrides the older one-word
stadium_ownership field in the club file, which it also keeps in step.
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

OWNER_TYPES = [
    {"key": "club", "label": "The club", "color": "#2a78d6"},
    {"key": "owner_company", "label": "The owner, not the club", "color": "#eb6834"},
    {"key": "council", "label": "The council", "color": "#1baf7a"},
    {"key": "landlord", "label": "Another landlord", "color": "#eda100"},
    {"key": "other_club", "label": "Another club", "color": "#e87ba4"},
    {"key": "unknown", "label": "Not established", "color": "#c8ced6"},
]
LABELS = {t["key"]: t["label"] for t in OWNER_TYPES}

# The one-word field the club files used before this research.
LEGACY = {"club": "club", "council": "council", "owner_company": "third_party",
          "landlord": "third_party", "other_club": "third_party"}

_cache: dict[Path, dict] = {}


def load(path: Path) -> dict[str, dict]:
    """{club_id: entry}. Missing file: empty. Read once per path."""
    path = Path(path)
    if path in _cache:
        return _cache[path]
    out: dict[str, dict] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for cid, entry in (data.get("grounds") or {}).items():
            if not isinstance(entry, dict) or entry.get("owner_type") not in LABELS:
                logger.warning("grounds.yml: skipping %s - no valid owner_type", cid)
                continue
            out[cid] = entry
    _cache[path] = out
    return out


def researched(path: Path) -> str:
    """The file's own note of when the research was done, e.g. "October 2026"."""
    path = Path(path)
    if not path.exists():
        return ""
    return str((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("researched") or "")


def merge(club_id: str, facts: dict, path: Path) -> dict:
    """The club's facts with its ground entry under `ground`, and the
    legacy stadium_ownership brought into line with it."""
    entry = load(path).get(club_id)
    if not entry:
        return facts
    facts = dict(facts)
    facts["ground"] = entry
    if entry.get("disputed"):
        facts["stadium_ownership"] = "disputed"
    elif entry["owner_type"] in LEGACY:
        facts["stadium_ownership"] = LEGACY[entry["owner_type"]]
    return facts


def years_left(entry: dict, year: int) -> int | None:
    end = entry.get("lease_end")
    return int(end) - year if isinstance(end, int) else None


def security(entry: dict | None, year: int) -> float | None:
    """
    0..1: how safely the club holds its home, for the value page.
    Owning it is 1; a long lease is most of the way there; a ground the
    owner holds apart from the club is worth less than it looks, because
    a buyer of the club does not get it. Unknown is None.
    """
    if not entry or entry.get("owner_type") in (None, "unknown"):
        return None
    if entry.get("disputed"):
        return 0.0
    kind = entry["owner_type"]
    if kind == "club":
        return 1.0
    if kind == "owner_company":
        return 0.4
    if kind == "other_club":
        return 0.1
    left = years_left(entry, year)
    long_, mid, short = (0.75, 0.5, 0.35) if kind == "council" else (0.6, 0.35, 0.2)
    if left is None:
        return short
    return long_ if left >= 50 else mid if left >= 10 else short


def describe(entry: dict, year: int) -> str:
    """One line for the facts panel: who, and for how long."""
    kind = entry["owner_type"]
    if kind == "unknown":
        return "Not established"
    text = {"club": "Owned by the club", "owner_company": "Owned by the owner, not the club",
            "council": "Council-owned", "landlord": "Owned by a landlord",
            "other_club": "Tenant of another club"}[kind]
    if entry.get("owner_name") and kind != "club":
        text += f": {entry['owner_name']}"
    left = years_left(entry, year)
    if left is not None:
        text += f"; lease to {entry['lease_end']}" + (" – expired" if left < 0 else "")
    elif entry.get("lease_note") and kind != "club":
        text += f"; {entry['lease_note']}"
    if entry.get("disputed"):
        text += " – disputed"
    return text
