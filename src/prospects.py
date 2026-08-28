"""
The acquisition screen: which fallen club is worth buying.

The thesis this scores is a specific one. A club with a high historical
ceiling, now several tiers below it after a financial collapse, still
holding its ground, in a catchment nobody bigger is competing for. The
bet is that the distress is priced in and the catchment is not.

Three things about the scoring are deliberate and worth stating, because
each is a way this kind of screen usually goes wrong.

FIRST, A MISSING INPUT IS NOT A ZERO. Ground tenure has to be researched
club by club and mostly has not been. A club nobody has checked must score
as `unknown` and be visibly flagged, not quietly sink to the bottom of the
table as though it had been checked and failed.

SECOND, THE BANDS ARE NOT COMPARABLE AND ARE NOT MERGED. A former third-
tier club and a club that peaked in the National League are different
bets - the first has latent demand the second never had - so they are
ranked within bands and never against each other.

THIRD, A DEAD COMPANY IS NOT A DISQUALIFIER. The best-positioned
candidates in the data - Workington, Scarborough, Hereford - are all
clubs whose company was wound up. That is the source of the discount
being bought, so band B exists to hold them rather than to exclude them.

Without club_catchment populated this module will not produce a ranking at
all. Ceiling and fall alone would rank on nostalgia, which is the half of
the thesis that is free; the catchment is the half that is scarce. See
docs/catchment-data.md.
"""

import argparse
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Weights are judgement and they decide the order, so they are named.
WEIGHTS = {
    "catchment": 3.0,     # the scarce half of the thesis
    "uncontested": 2.0,   # having it to yourself
    "ceiling": 1.5,       # how high the club has been
    "fall": 1.0,          # how far it has to climb back, i.e. how cheap
    "recency": 1.5,       # latent demand decays; a 40-year absence is not a fanbase
    "income": 1.0,        # ability to pay
    "tenure": 2.0,        # owning the ground
}

# Beyond this the supporters, the staff and usually the ground have all
# dispersed, and what is left is a name. Bangor City last appear in 1984;
# whatever could be bought there is not the thing this screen is looking
# for. Excluded rather than ranked low, and the count is reported.
STALE_AFTER_SEASONS = 25

TENURE_SCORES = {
    "freehold": 1.0,
    "leasehold_long": 0.6,
    "leasehold_short": 0.3,
    "council": 0.2,
    "none": 0.0,
}

BAND_LABELS = {
    "A": "Football League ceiling, club still trading",
    "B": "Football League ceiling, company wound up",
    "C": "National League ceiling",
}


def _normalise(values: dict[str, float], invert: bool = False) -> dict[str, float]:
    """
    Scale to 0-1 across the candidates actually present. Clubs with no
    value are absent from the result rather than scored zero.
    """
    present = {k: v for k, v in values.items() if v is not None}
    if not present:
        return {}
    lo, hi = min(present.values()), max(present.values())
    if hi == lo:
        return {k: 0.5 for k in present}
    out = {k: (v - lo) / (hi - lo) for k, v in present.items()}
    return {k: (1.0 - v if invert else v) for k, v in out.items()}


def _load_prospect_facts() -> dict[str, dict]:
    """
    Hand-researched facts from club_prospects.csv: ground tenure, and
    whether control of the club can be bought at all.

    The file may not exist, and a row may be half-filled. Absence means
    unknown - for that field, for that club - and the screen says so
    rather than assuming the worst. `unknown` is stored explicitly rather
    than omitted, because "nobody has checked" and "checked and it is bad"
    must not converge on the same score.
    """
    path = PROJECT_ROOT / "club_prospects.csv"
    if not path.exists():
        return {}
    import csv
    out: dict[str, dict] = {}
    with path.open() as fh:
        for row in csv.DictReader(fh):
            cid = (row.get("club_id") or "").strip()
            if not cid:
                continue
            tenure = (row.get("ground_tenure") or "").strip().lower() or "unknown"
            buyable = (row.get("purchasable") or "").strip().lower() or "unknown"
            out[cid] = {
                "tenure": tenure,
                "source": (row.get("tenure_source_url") or "").strip(),
                "purchasable": buyable,
                "ownership_note": (row.get("ownership_note") or "").strip(),
                # Whose ceiling is it? For most fallen clubs the standings
                # belong to a company that no longer exists, and the thing
                # on sale is a successor that bought the name. Ranking on
                # the dead club's peak buys the wrong company's history.
                "peak_entity": (row.get("peak_tier_entity") or "").strip().lower()
                               or "unknown",
                # The live club's own ceiling, where the recorded one was
                # reached by a company that no longer exists.
                "successor_peak": int(row["successor_peak_tier"])
                                  if (row.get("successor_peak_tier") or "").strip() else None,
                "entity_note": (row.get("entity_note") or "").strip(),
            }
    return out


def candidates(conn: sqlite3.Connection) -> list[dict]:
    """
    Every club that has fallen below the Football League, with the raw
    inputs attached. Banded, not yet scored.
    """
    peaks = dict(conn.execute(
        "SELECT club_id, MIN(tier) FROM standings GROUP BY club_id"))
    lasts = dict(conn.execute(
        "SELECT club_id, MAX(season_end_year) FROM standings GROUP BY club_id"))
    latest = conn.execute(
        "SELECT MAX(season_end_year) FROM standings").fetchone()[0]

    try:
        catch = {r[0]: r for r in conn.execute(
            "SELECT club_id, catchment_pop_restored, catchment_income,"
            " contest_ratio, nearest_rival_id, nearest_rival_miles"
            " FROM club_catchment")}
    except sqlite3.Error:
        catch = {}

    docked = {r[0] for r in conn.execute(
        "SELECT DISTINCT club_id FROM points_deductions WHERE applied = 1")}

    # A club whose identity has already been carried on by a successor is
    # not for sale: the thing an investor would be buying has moved. Only
    # Wimbledon/AFC Wimbledon is modelled this way in the data today, but
    # the check is on the relationship rather than the name.
    successors = {
        parent: child for child, parent in conn.execute(
            "SELECT club_id, lineage_parent_id FROM club_master"
            " WHERE lineage_parent_id IS NOT NULL")
    }

    facts = _load_prospect_facts()
    out = []
    for club_id, name, current in conn.execute(
        "SELECT club_id, canonical_name, current_tier FROM club_master"
    ):
        peak = peaks.get(club_id)
        if peak is None or current is None:
            continue

        # Still in the Football League or the National League: not fallen.
        if current in (1, 2, 3, 4, 5):
            continue
        # Never got high enough for the thesis to mean anything.
        if peak > 5:
            continue

        # Which band depends on WHOSE Football League ceiling it is. This
        # used to key off current_tier == 0, which stopped identifying a
        # wound-up company once that column was corrected to record where
        # the successor actually plays.
        known = facts.get(club_id)
        entity = known["peak_entity"] if known else ("predecessor" if current == 0
                                                     else "unknown")
        if peak <= 4 and entity == "predecessor":
            band = "B"
        elif peak <= 4:
            band = "A"
        elif peak == 5:
            band = "C"
        else:
            continue

        row = catch.get(club_id)
        out.append({
            "club_id": club_id,
            "name": name,
            "band": band,
            "peak_tier": peak,
            "current_tier": current,
            "last_season": lasts.get(club_id),
            "seasons_gone": (latest - lasts[club_id]) if club_id in lasts else None,
            "catchment_pop": row[1] if row else None,
            "catchment_income": row[2] if row else None,
            "contest_ratio": row[3] if row else None,
            "nearest_rival": row[4] if row else None,
            "nearest_rival_miles": row[5] if row else None,
            "tenure": known["tenure"] if known else "unknown",
            "purchasable": known["purchasable"] if known else "unknown",
            "ownership_note": known["ownership_note"] if known else "",
            "peak_entity": known["peak_entity"] if known else "unknown",
            "successor_peak": known["successor_peak"] if known else None,
            "entity_note": known["entity_note"] if known else "",
            "was_docked": club_id in docked,
            "successor": successors.get(club_id),
        })
    return out


def score(rows: list[dict]) -> list[dict]:
    """
    Attach a 0-1 score to each candidate, plus the inputs that went into
    it and the ones that were missing.

    The denominator is the weight of the inputs actually available, so a
    club missing tenure is scored on the rest rather than penalised for
    not having been researched. `missing` carries what was absent, and
    nothing should be ranked without reading it.
    """
    norm = {
        "catchment": _normalise({r["club_id"]: r["catchment_pop"] for r in rows}),
        "income": _normalise({r["club_id"]: r["catchment_income"] for r in rows}),
        "uncontested": _normalise(
            {r["club_id"]: r["contest_ratio"] for r in rows}, invert=True),
        # A lower tier number is a higher ceiling, so invert.
        # Rank on the ceiling the club being bought actually reached. An
        # inherited ceiling belongs to a dead company and buying on it
        # prices the wrong club's history.
        "ceiling": _normalise(
            {r["club_id"]: (r["successor_peak"] or r["peak_tier"]) for r in rows},
            invert=True),
        "fall": _normalise(
            {r["club_id"]: (r["current_tier"] or 7) - r["peak_tier"] for r in rows}),
        "recency": _normalise(
            {r["club_id"]: r["seasons_gone"] for r in rows}, invert=True),
    }

    for r in rows:
        parts, missing, total_w, got = {}, [], 0.0, 0.0
        for key, weight in WEIGHTS.items():
            if key == "tenure":
                if r["tenure"] == "unknown":
                    missing.append("tenure")
                    continue
                value = TENURE_SCORES.get(r["tenure"])
                if value is None:
                    missing.append(f"tenure({r['tenure']}?)")
                    continue
            else:
                value = norm[key].get(r["club_id"])
                if value is None:
                    missing.append(key)
                    continue
            parts[key] = round(value, 3)
            total_w += weight
            got += weight * value

        r["parts"] = parts
        r["missing"] = missing
        r["score"] = round(got / total_w, 4) if total_w else None
    return rows


def screen(conn: sqlite3.Connection) -> dict:
    """
    The whole screen: candidates, scored, grouped by band. `blocked` is
    set when the catchment model has not run, in which case no ranking is
    produced at all - see the module docstring.
    """
    everything = candidates(conn)

    excluded = []
    live = []
    for r in everything:
        # A club nobody can buy is not a bad investment - it is not an
        # investment. Kept separate from the score so it cannot be
        # mistaken for a club that merely ranks badly.
        if r["purchasable"] == "no":
            note = r["ownership_note"] or "control cannot be acquired"
            r["excluded"] = f"not for sale: {note}"
            excluded.append(r)
        elif r["successor"]:
            r["excluded"] = f"identity carried on by {r['successor']}"
            excluded.append(r)
        elif (r["seasons_gone"] or 0) > STALE_AFTER_SEASONS:
            r["excluded"] = f"absent {r['seasons_gone']} seasons"
            excluded.append(r)
        else:
            live.append(r)

    rows = score(live)
    have_catchment = any(r["catchment_pop"] is not None for r in rows)
    bands = {b: [] for b in BAND_LABELS}
    for r in rows:
        bands[r["band"]].append(r)
    for b in bands:
        bands[b].sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
    return {
        "bands": bands,
        "excluded": excluded,
        "blocked": None if have_catchment else (
            "club_catchment is empty, so no ranking is produced. Ceiling and "
            "fall alone would rank on nostalgia, which is the free half of "
            "the thesis. See docs/catchment-data.md."
        ),
    }


def render(result: dict) -> str:
    lines = []
    if result["blocked"]:
        lines += ["", "  NOT RANKED — " + result["blocked"], ""]

    for band, label in BAND_LABELS.items():
        rows = result["bands"][band]
        if not rows:
            continue
        lines.append("")
        lines.append(f"Band {band} — {label}  ({len(rows)})")
        lines.append(f"  {'club':26} {'score':>6} {'peak':>4} {'now':>4} "
                     f"{'catchment':>10} {'contest':>8} {'tenure':>9}  notes")
        for r in rows:
            score_s = "  —  " if r["score"] is None else f"{r['score']:.3f}"
            pop = "—" if r["catchment_pop"] is None else f"{r['catchment_pop']:,}"
            con = "—" if r["contest_ratio"] is None else f"{r['contest_ratio']*100:.0f}%"
            notes = []
            if r["nearest_rival_miles"] is not None:
                notes.append(f"{r['nearest_rival']} {r['nearest_rival_miles']:.0f}mi")
            if r["peak_entity"] == "predecessor":
                sp = r["successor_peak"]
                notes.append(f"recorded peak {r['peak_tier']} is a dead predecessor"
                             + (f", live club reached {sp}" if sp else ""))
            if r["was_docked"]:
                notes.append("docked")
            if r["missing"]:
                notes.append("missing: " + ",".join(r["missing"]))
            lines.append(
                f"  {r['name'][:26]:26} {score_s:>6} {r['peak_tier']:>4} "
                f"{r['current_tier']:>4} {pop:>10} {con:>8} "
                f"{r['tenure']:>9}  {'; '.join(notes)}")

    inherited = [r for band in result["bands"].values() for r in band
                 if r["peak_entity"] == "predecessor"]
    if inherited:
        lines.append("")
        lines.append("  Ceilings marked above belong to a company that no longer "
                     "exists. The")
        lines.append("  successor bought a name, not a record - rank on it and you "
                     "are pricing")
        lines.append("  the wrong club's history.")

    dropped = result.get("excluded") or []
    if dropped:
        lines.append("")
        lines.append(f"Excluded ({len(dropped)}) — not ranked, and why")
        for r in sorted(dropped, key=lambda r: r["name"]):
            lines.append(f"  {r['name'][:26]:26} {r['excluded']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--db", type=Path,
                        default=PROJECT_ROOT / "data" / "db" / "england.db")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    print(render(screen(conn)))


if __name__ == "__main__":
    main()
