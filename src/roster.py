"""
The roster: clubs that compete for people but have no league history here.

This site records tiers 1 to 5. The catchment model, though, is a model of
COMPETITION, and competition does not stop at the fifth tier. Every club
below it still takes a share of the people around it, and until this
module existed the model could not see any club that had never been in the
top five - so it credited their neighbours with towns that are not free.

That distortion falls hardest exactly where the acquisition screen looks.
A club that has fallen to the sixth tier is surrounded by sixth- and
seventh-tier neighbours, none of which the model knew about, so its
catchment was flattered and its contest ratio understated. Adding the
roster does not add candidates - a club with no standings rows cannot have
a Football League ceiling and cannot be a prospect - it makes the answers
about the existing candidates honest.

WHY A SEPARATE FILE AND TABLE. club_master.csv is the identity spine of
the whole pipeline: entities.seed_club_master deletes any DB row missing
from it and NULLs that club's standings rows, and name-variant collisions
between clubs resolve by alphabetical accident. Putting two hundred
non-league names into it to obtain a coordinate would risk the league
history for no gain. So the roster lives alongside it and is joined only
where it is needed, in catchment._club_frame. The one rule the two files
must obey is that no club appears in both: a club counted twice competes
with itself and halves its own share, which is why _validate rejects it
outright rather than warning.

PRECISION IS RECORDED, NOT ASSUMED. Ground coordinates are published for
some of these clubs and not for others. Where a ground could not be
placed, the club sits at the population-weighted centroid of its town,
computed from the ONS MSOA data already in the database, and the row says
so in location_precision. A town-level coordinate is honest at the scale
this model works at - it is the difference between two streets, not two
towns - but it is not the same fact as a surveyed ground, and a reader
comparing two clubs is entitled to know which they are looking at.

NO PEAK COLUMN. A roster club's ceiling is its current tier by
construction: anything that had reached the fifth tier would be in
club_master with the standings to prove it. So the restored counterfactual
in the catchment model leaves these clubs where they are, which is right -
they are the competition, not the investment.
"""

import csv
import logging
import re
import sqlite3
from pathlib import Path

import catchment

logger = logging.getLogger(__name__)

CREATE_CLUB_ROSTER_SQL = """
CREATE TABLE IF NOT EXISTS club_roster (
    club_id             TEXT PRIMARY KEY,
    canonical_name      TEXT NOT NULL,
    tier                INT  NOT NULL,
    division            TEXT,
    ground_name         TEXT,
    latitude            REAL NOT NULL,
    longitude           REAL NOT NULL,
    location_precision  TEXT NOT NULL,
    locality            TEXT,
    source_url          TEXT,
    notes               TEXT
);
"""

ROSTER_COLUMNS = [
    "club_id", "canonical_name", "tier", "division", "ground_name",
    "latitude", "longitude", "location_precision", "locality",
    "source_url", "notes",
]

REQUIRED_COLUMNS = {"club_id", "canonical_name", "tier", "latitude", "longitude",
                    "location_precision"}

PRECISIONS = {"ground", "town"}

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def slugify(name: str) -> str:
    """
    A club name to the form club ids take.

    Hand-written ids are permanent and a typo in one is invisible, so the
    tests use this to check that every id in the roster still starts with
    its own club's name. It is not enough on its own to mint an id: the
    suffix a club actually uses - FC, AFC, or none - is part of its
    identity and is not derivable from the name.
    """
    text = name.strip().lower().replace("&", " and ")
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _validate(row: dict, master_ids: set[str]) -> list[str]:
    """Problems that would make a row wrong rather than merely sparse."""
    problems = []
    cid = row["club_id"]

    if not SLUG_RE.match(cid):
        problems.append(f"club_id {cid!r} is not a slug")
    if not slugify(row["canonical_name"]) or not cid.startswith(
            slugify(row["canonical_name"])):
        problems.append(
            f"club_id {cid!r} does not start with slugify({row['canonical_name']!r})")

    # The one that must never be a warning. A club in both files is two
    # clubs to the model: it competes with itself, and each copy takes
    # roughly half the share the real club should have.
    if cid in master_ids:
        problems.append("already in club_master - would be counted twice")

    tier = row["tier"]
    if tier is None:
        problems.append("missing tier")
    elif tier not in catchment.TIER_ATTRACTIVENESS:
        # Falling through to DEFAULT_ATTRACTIVENESS would give a step-6
        # club the same pull as a step-3 one, silently.
        problems.append(f"tier {tier} has no weight in TIER_ATTRACTIVENESS")

    lat, lon = row["latitude"], row["longitude"]
    if lat is None or lon is None:
        problems.append("missing coordinates")
    else:
        lo, hi = catchment.ENGLAND_BOUNDS["lat"]
        if not lo <= lat <= hi:
            problems.append(f"latitude {lat} outside England")
        lo, hi = catchment.ENGLAND_BOUNDS["lon"]
        if not lo <= lon <= hi:
            problems.append(f"longitude {lon} outside England")

    if row["location_precision"] not in PRECISIONS:
        problems.append(
            f"location_precision {row['location_precision']!r} not in {sorted(PRECISIONS)}")

    return problems


def _coerce(raw: dict) -> dict:
    row = {}
    for col in ROSTER_COLUMNS:
        value = (raw.get(col) or "").strip()
        if col in ("latitude", "longitude"):
            try:
                row[col] = float(value) if value else None
            except ValueError:
                row[col] = None
        elif col == "tier":
            try:
                row[col] = int(value) if value else None
            except ValueError:
                row[col] = None
        else:
            row[col] = value or None
    return row


def seed_club_roster(conn: sqlite3.Connection, csv_path: Path) -> int:
    """
    Load club_roster.csv into club_roster.

    Follows finances.seed_club_finances and catchment.seed_msoa_demographics:
    read as text, coerce, validate, drop rows that would mislead, and
    delete rows that have left the CSV so the table never outlives its
    source. Absence of the file is not an error - the model simply goes
    back to seeing only the clubs with league history.
    """
    conn.execute(CREATE_CLUB_ROSTER_SQL)

    if not csv_path.exists():
        logger.info("No %s - catchment will see only clubs with league history",
                    csv_path.name)
        return 0

    master_ids = {r[0] for r in conn.execute("SELECT club_id FROM club_master")}

    rows, ids, skipped = [], set(), 0
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{csv_path.name} missing columns: {sorted(missing)}")

        for raw in reader:
            row = _coerce(raw)
            if not row["club_id"]:
                skipped += 1
                continue
            if row["club_id"] in ids:
                logger.warning("Skipping duplicate roster club_id %s", row["club_id"])
                skipped += 1
                continue

            problems = _validate(row, master_ids)
            if problems:
                logger.warning("Skipping roster club %s: %s",
                               row["club_id"], "; ".join(problems))
                skipped += 1
                continue

            ids.add(row["club_id"])
            rows.append(tuple(row[c] for c in ROSTER_COLUMNS))

    db_ids = {r[0] for r in conn.execute("SELECT club_id FROM club_roster")}
    stale = sorted(db_ids - ids)
    if stale:
        logger.warning("Removing %d roster row(s) no longer in the CSV: %s",
                       len(stale), ", ".join(stale))
        conn.executemany("DELETE FROM club_roster WHERE club_id = ?",
                         [(c,) for c in stale])

    placeholders = ",".join("?" * len(ROSTER_COLUMNS))
    conn.executemany(
        f"INSERT OR REPLACE INTO club_roster ({','.join(ROSTER_COLUMNS)})"
        f" VALUES ({placeholders})",
        rows,
    )
    conn.commit()

    if skipped:
        logger.warning("club_roster: %d row(s) skipped as unusable", skipped)
    by_tier = {}
    for row in rows:
        by_tier[row[2]] = by_tier.get(row[2], 0) + 1
    logger.info("Seeded club_roster with %d rows (%s)", len(rows),
                ", ".join(f"tier {t}: {n}" for t, n in sorted(by_tier.items())))
    return len(rows)
