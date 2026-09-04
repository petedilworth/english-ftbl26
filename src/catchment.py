"""
Catchment: how many people a club can plausibly draw on, and who else is
competing for them.

This exists because distance to the nearest rival - the obvious measure,
and the one this repo could already compute from club_master coordinates -
ranks clubs backwards. Workington is 54.7 miles from the nearest tier 1-4
club, the most isolated position in the data, and most of that radius is
the Lake District and the Irish Sea. Maidstone is 7.4 miles from
Gillingham and sits in dense commuter Kent. On distance Workington wins by
a mile; on people it may well lose. A screen ranking on distance would
prefer empty moorland to a contested town, which is the wrong answer.

So catchment is measured in people, not miles, using a Huff gravity model
over MSOA population. Every MSOA's population is split across every club
in proportion to that club's pull and the inverse square of its distance:

    share(m, c) = (A_c / d(m,c)^beta) / sum_j (A_j / d(m,j)^beta)

A_c is an attractiveness weight by tier - a Premier League club draws from
much further than a National League one - and beta controls how fast
interest decays with distance.

Two properties make this worth the arithmetic rather than a radius count:

- A club next door to a bigger one loses almost all of its share.
  Bradford Park Avenue is 3.3 miles from Bradford City, and a radius model
  would credit it with the whole of Bradford.
- Population still has to be there. Isolation alone earns nothing.

THE COUNTERFACTUAL. Each club is scored twice: once at its current tier,
and once as if restored to its historical ceiling, with every other club
held at its current tier. The restored figure is the one the investment
case turns on, because what is being bought is the option to get back
there - not the club as it stands.

MODEL_VERSION is stored on every row. The weights and beta below are
judgement, they decide the ranking, and a re-tune must be traceable.
"""

import logging
import math
import sqlite3
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

MODEL_VERSION = "gravity-v1-beta2"

# How much further a bigger club draws from. Judgement, not measurement:
# these numbers decide the answer, so they are here, named, and versioned
# rather than buried in the arithmetic. Tier 0 is a club whose company is
# dead - it currently competes for nobody, which is why the restored
# counterfactual exists.
TIER_ATTRACTIVENESS = {
    1: 100.0,   # Premier League - national draw
    2: 40.0,    # Championship
    3: 15.0,    # League One
    4: 8.0,     # League Two
    5: 4.0,     # National League
    6: 2.0,     # National League North/South
    7: 1.0,     # step 3
    8: 0.7,
    9: 0.5,
    10: 0.35,
    0: 0.0,     # no successor plays anywhere: exerts no pull
}
DEFAULT_ATTRACTIVENESS = 1.0

# Inverse-square decay. Beta 1 spreads interest implausibly far; beta 3
# makes every club purely local and collapses the contest measure.
BETA = 2.0

# Below this the gravity term explodes. A club is not infinitely
# attractive to the street outside it.
MIN_DISTANCE_MILES = 0.5

EARTH_RADIUS_MILES = 3958.8

REQUIRED_MSOA_COLUMNS = {"msoa_code", "latitude", "longitude", "population"}

CREATE_MSOA_DEMOGRAPHICS_SQL = """
CREATE TABLE IF NOT EXISTS msoa_demographics (
    msoa_code        TEXT PRIMARY KEY,
    msoa_name        TEXT,
    local_authority  TEXT,
    latitude         REAL NOT NULL,
    longitude        REAL NOT NULL,
    population       INT  NOT NULL,
    population_year  INT,
    net_income       INT,
    net_income_year  INT,
    income_ci_lower  INT,
    income_ci_upper  INT,
    source_url       TEXT
);
"""

CREATE_CLUB_CATCHMENT_SQL = """
CREATE TABLE IF NOT EXISTS club_catchment (
    club_id                  TEXT PRIMARY KEY,
    catchment_pop_current    INT,
    catchment_pop_restored   INT,
    catchment_income         INT,
    voronoi_pop              INT,
    contest_ratio            REAL,
    nearest_rival_id         TEXT,
    nearest_rival_miles      REAL,
    nearest_rival_tier       INT,
    model_version            TEXT NOT NULL
);
"""

MSOA_COLUMNS = [
    "msoa_code", "msoa_name", "local_authority", "latitude", "longitude",
    "population", "population_year", "net_income", "net_income_year",
    "income_ci_lower", "income_ci_upper", "source_url",
]

CATCHMENT_COLUMNS = [
    "club_id", "catchment_pop_current", "catchment_pop_restored",
    "catchment_income", "voronoi_pop", "contest_ratio", "nearest_rival_id",
    "nearest_rival_miles", "nearest_rival_tier", "model_version",
]

# England's bounding box, generously drawn. A centroid outside it is a
# transcription error, not a place.
ENGLAND_BOUNDS = {"lat": (49.8, 55.9), "lon": (-6.5, 2.1)}


CREATE_MSOA_ASSIGNMENT_SQL = """
CREATE TABLE IF NOT EXISTS msoa_assignment (
    msoa_code   TEXT PRIMARY KEY,
    club_id     TEXT NOT NULL,
    kept_share  REAL,
    FOREIGN KEY (club_id) REFERENCES club_master(club_id)
)
"""


def great_circle_miles(lat1: float, lon1: float,
                       lat2: float, lon2: float) -> float:
    """
    Distance between two points on the earth, in miles.

    The single home for this calculation. It had been rewritten by hand in
    throwaway scripts several times over, each copy a chance to get the
    radius or the hemisphere wrong, and every distance the site quotes now
    comes through here.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def attractiveness(tier: int | None) -> float:
    """Pull weight for a club at a given tier. Unknown tiers draw locally."""
    if tier is None:
        return DEFAULT_ATTRACTIVENESS
    return TIER_ATTRACTIVENESS.get(int(tier), DEFAULT_ATTRACTIVENESS)


def _int_or_none(value) -> int | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _float_or_none(value) -> float | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _text_or_none(value) -> str | None:
    text = str(value).strip()
    return text or None


def _validate_msoa(row: dict) -> list[str]:
    """Problems that would make a row misleading rather than merely sparse."""
    problems = []
    lat, lon = row.get("latitude"), row.get("longitude")

    if lat is None or lon is None:
        problems.append("missing centroid")
    else:
        lo, hi = ENGLAND_BOUNDS["lat"]
        if not lo <= lat <= hi:
            problems.append(f"latitude {lat} outside England")
        lo, hi = ENGLAND_BOUNDS["lon"]
        if not lo <= lon <= hi:
            problems.append(f"longitude {lon} outside England")

    pop = row.get("population")
    if pop is None or pop <= 0:
        problems.append(f"population {pop!r} is not a positive count")

    lower, upper = row.get("income_ci_lower"), row.get("income_ci_upper")
    income = row.get("net_income")
    if lower is not None and upper is not None and lower > upper:
        problems.append("income confidence interval is inverted")
    if income is not None and lower is not None and upper is not None:
        if not lower <= income <= upper:
            problems.append("net_income sits outside its own confidence interval")

    return problems


def seed_msoa_demographics(conn: sqlite3.Connection, csv_path: Path) -> int:
    """
    Load MSOA population and income from CSV into msoa_demographics.

    Follows the shape of finances.seed_club_finances: read as text, coerce
    per column, validate, drop rows that would mislead, and remove rows
    that have left the CSV so the table never outlives its source.
    """
    conn.execute(CREATE_MSOA_DEMOGRAPHICS_SQL)

    if not csv_path.exists():
        logger.info("No %s - skipping catchment (charts will be empty)",
                    csv_path.name)
        return 0

    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    missing = REQUIRED_MSOA_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"{csv_path.name} missing columns: {sorted(missing)}")

    rows, codes, skipped = [], set(), 0
    for _, raw in df.iterrows():
        row = {"msoa_code": _text_or_none(raw["msoa_code"])}
        for col in MSOA_COLUMNS:
            if col == "msoa_code":
                continue
            if col in ("latitude", "longitude"):
                row[col] = _float_or_none(raw[col]) if col in df.columns else None
            elif col in ("population", "population_year", "net_income",
                         "net_income_year", "income_ci_lower", "income_ci_upper"):
                row[col] = _int_or_none(raw[col]) if col in df.columns else None
            else:
                row[col] = _text_or_none(raw[col]) if col in df.columns else None

        if not row["msoa_code"]:
            skipped += 1
            continue

        problems = _validate_msoa(row)
        if problems:
            logger.warning("Skipping MSOA %s: %s",
                           row["msoa_code"], "; ".join(problems))
            skipped += 1
            continue

        codes.add(row["msoa_code"])
        rows.append(tuple(row[c] for c in MSOA_COLUMNS))

    db_codes = {r[0] for r in conn.execute("SELECT msoa_code FROM msoa_demographics")}
    stale = sorted(db_codes - codes)
    if stale:
        logger.warning("Removing %d MSOA row(s) no longer in the CSV", len(stale))
        conn.executemany("DELETE FROM msoa_demographics WHERE msoa_code = ?",
                         [(c,) for c in stale])

    placeholders = ",".join("?" * len(MSOA_COLUMNS))
    conn.executemany(
        f"INSERT OR REPLACE INTO msoa_demographics ({','.join(MSOA_COLUMNS)})"
        f" VALUES ({placeholders})",
        rows,
    )
    conn.commit()

    if skipped:
        logger.warning("msoa_demographics: %d row(s) skipped as unusable", skipped)
    logger.info("Seeded msoa_demographics with %d rows", len(rows))
    return len(rows)


def _club_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Every club with a location, its current tier, and its historical
    ceiling. The ceiling comes from the standings and falls back to the
    current tier for a club the data has never seen play.

    One source. The sixth- and seventh-tier clubs briefly lived in a
    separate club_roster table, because a club with no league history had
    nowhere else to go; they are in club_master now, with standings rows
    of their own, so the union that used to be here is gone.

    A club with no coordinates is simply absent from the model, which is
    the right answer for one whose current level this project does not
    record: it should not be given a pull it cannot justify.
    """
    clubs = pd.read_sql_query(
        "SELECT club_id, current_tier, latitude, longitude"
        " FROM club_master WHERE latitude IS NOT NULL AND longitude IS NOT NULL",
        conn,
    )
    peaks = pd.read_sql_query(
        "SELECT club_id, MIN(tier) AS peak_tier FROM standings GROUP BY club_id",
        conn,
    )
    clubs = clubs.merge(peaks, on="club_id", how="left")
    clubs["peak_tier"] = clubs["peak_tier"].fillna(clubs["current_tier"])

    return clubs


def rebuild_club_catchment(conn: sqlite3.Connection) -> int:
    """
    Recompute club_catchment from msoa_demographics and club_master.

    Cheap enough to run unconditionally on every pipeline pass: roughly
    180 clubs by 7,000 MSOAs is a 1.2M-cell matrix, which numpy does in
    well under a second. Storing it rather than computing it at render
    time keeps the model out of the site build and makes the numbers
    queryable from a screening script.
    """
    import numpy as np

    conn.execute(CREATE_CLUB_CATCHMENT_SQL)

    msoas = pd.read_sql_query(
        "SELECT msoa_code, latitude, longitude, population, net_income"
        " FROM msoa_demographics",
        conn,
    )
    clubs = _club_frame(conn)

    if msoas.empty or clubs.empty:
        logger.info("No MSOA or club coordinates - club_catchment left empty")
        conn.execute("DELETE FROM club_catchment")
        conn.commit()
        return 0

    # Great-circle distance, vectorised. Same formula as
    # great_circle_miles, which stays the readable reference.
    mlat = np.radians(msoas["latitude"].to_numpy())
    mlon = np.radians(msoas["longitude"].to_numpy())
    clat = np.radians(clubs["latitude"].to_numpy())[:, None]
    clon = np.radians(clubs["longitude"].to_numpy())[:, None]

    h = (np.sin((mlat - clat) / 2) ** 2
         + np.cos(clat) * np.cos(mlat) * np.sin((mlon - clon) / 2) ** 2)
    dist = 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.clip(h, 0, 1)))
    dist = np.maximum(dist, MIN_DISTANCE_MILES)

    decay = dist ** -BETA                                  # clubs x msoas
    a_current = np.array([attractiveness(t) for t in clubs["current_tier"]])
    a_restored = np.array([attractiveness(t) for t in clubs["peak_tier"]])

    pull_current = a_current[:, None] * decay
    pull_restored = a_restored[:, None] * decay
    denom = pull_current.sum(axis=0)                       # per MSOA

    pop = msoas["population"].to_numpy(dtype=float)
    income = msoas["net_income"].to_numpy(dtype=float)

    # Current: every club at the tier it is actually in.
    with np.errstate(divide="ignore", invalid="ignore"):
        share_current = np.where(denom > 0, pull_current / denom, 0.0)
    catch_current = share_current @ pop

    # Restored: this club at its ceiling, everyone else where they are.
    # Swapping one club's term in and its current term out is exact and
    # avoids rebuilding the denominator once per club.
    denom_restored = denom[None, :] - pull_current + pull_restored
    with np.errstate(divide="ignore", invalid="ignore"):
        share_restored = np.where(denom_restored > 0,
                                  pull_restored / denom_restored, 0.0)
    catch_restored = share_restored @ pop

    # Income of the people a restored club would actually draw, weighted
    # by how much of each MSOA it would command.
    weights = share_restored * pop
    has_income = ~np.isnan(income)
    inc_weight = weights[:, has_income]
    inc_total = inc_weight.sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        catch_income = np.where(
            inc_total > 0,
            (inc_weight @ np.nan_to_num(income[has_income])) / inc_total,
            np.nan,
        )

    # Voronoi: the whole of each MSOA to its nearest club. The natural
    # hinterland, before anyone competes for it.
    nearest = dist.argmin(axis=0)
    voronoi = np.zeros(len(clubs))
    np.add.at(voronoi, nearest, pop)

    # How much of that natural hinterland a restored club would lose to
    # its neighbours. 0 is uncontested, 1 is entirely taken.
    #
    # Numerator and denominator must range over the SAME areas, or the
    # measure is nonsense. Comparing a club's total gravity catchment
    # against its Voronoi cell mixes two populations: a club whose nearest
    # neighbour is very close has a tiny cell, so its catchment drawn from
    # further afield exceeds it and it scores as uncontested - precisely
    # backwards, and precisely the Bradford Park Avenue case. So restrict
    # to the areas the club is nearest to, and ask what share of those
    # people it actually keeps.
    kept_share = share_restored[nearest, np.arange(len(msoas))]
    own_share = kept_share * pop
    kept = np.zeros(len(clubs))
    np.add.at(kept, nearest, own_share)

    # The same assignment, stored per area rather than only summed per
    # club. contest_ratio says a club keeps 1.7% of the people nearest to
    # it; this is WHICH people, and how much of each, so the map can draw
    # the hinterland instead of asking a reader to picture it. Written
    # from the arrays that produced contest_ratio rather than recomputed,
    # so the picture and the number cannot disagree.
    conn.execute(CREATE_MSOA_ASSIGNMENT_SQL)
    conn.execute("DELETE FROM msoa_assignment")
    conn.executemany(
        "INSERT INTO msoa_assignment (msoa_code, club_id, kept_share)"
        " VALUES (?, ?, ?)",
        [(code, clubs["club_id"].iloc[int(j)], float(k))
         for code, j, k in zip(msoas["msoa_code"], nearest, kept_share)],
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        contest = np.where(voronoi > 0, 1.0 - (kept / voronoi), np.nan)
    contest = np.clip(contest, 0.0, 1.0)

    # Nearest rival club, and what tier it plays at.
    club_lat = clubs["latitude"].to_numpy()
    club_lon = clubs["longitude"].to_numpy()
    ids = clubs["club_id"].tolist()
    tiers = clubs["current_tier"].tolist()

    rows = []
    for i, cid in enumerate(ids):
        best_j, best_d = None, None
        for j in range(len(ids)):
            if j == i:
                continue
            d = great_circle_miles(club_lat[i], club_lon[i],
                                   club_lat[j], club_lon[j])
            if best_d is None or d < best_d:
                best_j, best_d = j, d
        rows.append((
            cid,
            int(round(catch_current[i])),
            int(round(catch_restored[i])),
            None if np.isnan(catch_income[i]) else int(round(catch_income[i])),
            int(round(voronoi[i])),
            None if np.isnan(contest[i]) else float(round(contest[i], 4)),
            ids[best_j] if best_j is not None else None,
            None if best_d is None else float(round(best_d, 2)),
            tiers[best_j] if best_j is not None else None,
            MODEL_VERSION,
        ))

    conn.execute("DELETE FROM club_catchment")
    placeholders = ",".join("?" * len(CATCHMENT_COLUMNS))
    conn.executemany(
        f"INSERT INTO club_catchment ({','.join(CATCHMENT_COLUMNS)})"
        f" VALUES ({placeholders})",
        rows,
    )
    conn.commit()
    logger.info("Rebuilt club_catchment with %d rows (%s)",
                len(rows), MODEL_VERSION)
    return len(rows)
