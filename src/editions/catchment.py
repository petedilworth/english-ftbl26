"""
The Wednesday catchment edition: whose people are this week's clubs
playing for?

Tied to the fixtures from Wednesday to the following Monday. Three
sections, each one claim in prose with a map as its evidence:

  The shared ground  - the fixture whose two clubs draw most on each
                       other's doorsteps.
  Bigger than their division
                     - the club playing this week whose market ranks
                       furthest above its place in the pyramid.
  Smaller than their division
                     - the reverse.

"Doorstep" is the model's turf: the neighbourhoods nearer a club's ground
than any other ground. Shares come from the catchment model with every
club at its current tier (catchment.current_shares) - the divisions as
they stand, not the restored counterfactual the site's contest figures
use. A club featured in the last four editions is not featured again.

The facts layer. Words are in templates/email/catchment.html and
editions/phrasing.py.
"""

import datetime
import logging
import sqlite3
from pathlib import Path

import catchment as model_mod
import fixtures as fixtures_mod
from editions import archive, config, maps, phrasing, render
from editions.base import Edition, EditionOutput
from editions.preview import TIER_NAMES, load_fixture_list

logger = logging.getLogger(__name__)

# Wednesday to the following Monday.
WINDOW_DAYS = 6
NO_REPEAT_EDITIONS = 4
TAKERS = 3

# The demographics are English MSOAs only (docs/catchment-data.md), so a
# Welsh club's doorstep is whatever sliver of England lies nearest its
# ground - Swansea's is north Devon, across the Bristol Channel. They are
# never featured. They stay in the model as takers, because their pull on
# English neighbourhoods is real.
OUTSIDE_ENGLAND = {"cardiff-city-fc", "swansea-city-fc", "newport-county-fc", "wrexham-fc"}


def recently_featured(n: int = NO_REPEAT_EDITIONS) -> set[str]:
    featured: set[str] = set()
    for doc in archive.all_claims("catchment")[-n:]:
        for claim in doc.get("claims") or []:
            featured.update(claim.get("featured") or [])
    return featured


def ladder(conn: sqlite3.Connection, season: int, eligible: set[str]) -> dict[str, dict]:
    """club_id -> tier, position and rank down the whole pyramid, tiers 1-5."""
    rows = conn.execute(
        "SELECT club_id, tier, position FROM standings"
        " WHERE season_end_year = ? AND tier BETWEEN 1 AND 5 AND club_id IS NOT NULL"
        " ORDER BY tier, position", (season,)).fetchall()
    out, rank = {}, 0
    for club_id, tier, position in rows:
        if club_id in eligible:
            rank += 1
            out[club_id] = {"tier": tier, "position": position, "ladder_rank": rank}
    return out


def market_ranks(model, clubs: set[str]) -> dict[str, int]:
    ordered = sorted(clubs, key=lambda c: -model.catchment[model.index[c]])
    return {c: n for n, c in enumerate(ordered, start=1)}


def doorstep(model, club_id: str, names: dict[str, str]) -> dict:
    turf = model.turf_people(club_id)
    kept = model.takes(club_id, club_id)
    return {
        "club_id": club_id, "name": names.get(club_id, club_id),
        "turf": turf, "kept": kept, "kept_pct": kept / turf if turf else 0.0,
        "catchment": float(model.catchment[model.index[club_id]]),
        "takers": [{"club_id": t, "name": names.get(t, t), "people": p,
                    "pct": p / turf if turf else 0.0}
                   for t, p in model.takers(club_id, TAKERS)],
    }


class CatchmentEdition(Edition):
    name = "catchment"

    def build(self, fixture_list: list[dict] | None = None,
              fixtures_file: Path | None = None) -> EditionOutput:
        conn, date = self.conn, self.date
        if fixture_list is None:
            fixture_list = load_fixture_list(conn, date, fixtures_file, window_days=WINDOW_DAYS)
        season = fixtures_mod.current_season_end_year(date)
        names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))
        model = model_mod.current_shares(conn)

        ctx = {"date": date, "sections": [], "thin": None,
               "archive_url": config.archive_url(self.name, date.isoformat()),
               "site_url": config.SITE_URL}
        claims = [{"featured": [], "lead": None}]
        images: list[tuple[Path, str]] = []
        refuse = None

        if not fixture_list:
            # As for the preview: an empty file is a missing input, not a
            # quiet week. The runner retries, then fails rather than sends.
            refuse = "no fixtures in the file for the next six days; not sending"
            ctx["thin"] = phrasing.thin_catchment_no_fixtures()
        elif model is None:
            ctx["thin"] = phrasing.thin_catchment_no_model()

        if model is not None and fixture_list:
            english = {c for c in model.index if c not in OUTSIDE_ENGLAND}
            standing = ladder(conn, season, english)
            ranked = set(standing)
            markets = market_ranks(model, ranked)
            playing = {}
            for f in fixture_list:
                for side in ("home", "away"):
                    cid = f.get(f"{side}_id")
                    if cid in ranked:
                        playing.setdefault(cid, f)
            avoid = recently_featured()

            # The shared ground: most people each club draws off the other's doorstep.
            best = None
            for f in fixture_list:
                a, b = f.get("home_id"), f.get("away_id")
                if a in ranked and b in ranked:
                    shared = model.takes(a, b) + model.takes(b, a)
                    if best is None or shared > best[0]:
                        best = (shared, f)
            used: set[str] = set()
            if best:
                f = best[1]
                a, b = f["home_id"], f["away_id"]
                da, db = doorstep(model, a, names), doorstep(model, b, names)
                # What the opponent draws off each club's own doorstep.
                da["opponent_takes"] = model.takes(b, a)
                db["opponent_takes"] = model.takes(a, b)
                third = next((t["club_id"] for t in da["takers"] + db["takers"]
                              if t["club_id"] not in (a, b)), None)
                cid = "map-lead"
                path = maps.catchment_map(model, [a, b] + ([third] if third else []), names,
                                          self.chart_dir / f"{cid}.png", region_of=[a, b])
                section = {"kind": "shared", "fixture": f, "home": da, "away": db, "cid": None}
                if path:
                    section["cid"] = cid
                    images.append((path, cid))
                section["text"] = phrasing.shared_ground(f, da, db)
                ctx["sections"].append(section)
                claims[0]["lead"] = [a, b]
                used |= {a, b}

            # Bigger and smaller than their division.
            candidates = [c for c in playing if c not in used and c not in avoid]
            for kind, key in (("bigger", lambda c: standing[c]["ladder_rank"] - markets[c]),
                              ("smaller", lambda c: markets[c] - standing[c]["ladder_rank"])):
                pool = [c for c in candidates if c not in used and key(c) > 0]
                if not pool:
                    continue
                club = max(pool, key=lambda c: (key(c), -markets[c]))
                d = doorstep(model, club, names)
                d.update(standing[club])
                d["market_rank"] = markets[club]
                d["division"] = TIER_NAMES.get(d["tier"], f"Tier {d['tier']}")
                cid = f"map-{kind}"
                focus = [club] + [t["club_id"] for t in d["takers"][:2]]
                # Frame the club's doorstep and its two biggest rivals', so
                # the map shows where its pull gives out.
                path = maps.catchment_map(model, focus, names, self.chart_dir / f"{cid}.png",
                                          region_of=focus)
                section = {"kind": kind, "club": d, "fixture": playing[club], "cid": None,
                           "clubs_ranked": len(ranked)}
                if path:
                    section["cid"] = cid
                    images.append((path, cid))
                section["text"] = phrasing.market_section(kind, d, playing[club], len(ranked), names)
                ctx["sections"].append(section)
                used.add(club)

            claims[0]["featured"] = sorted(used)
            if not ctx["sections"] and not ctx["thin"]:
                ctx["thin"] = phrasing.thin_catchment_no_story()

        subject = phrasing.catchment_subject(ctx)
        html = render.render("catchment.html", **ctx)
        return EditionOutput(subject=subject, html=html, text=self._text(ctx),
                             images=images, claims=claims, thin=ctx["thin"], refuse=refuse)

    @staticmethod
    def _text(ctx: dict) -> str:
        lines = [f"CATCHMENT - {ctx['date']:%d %B %Y}", ""]
        if ctx["thin"]:
            lines.append(ctx["thin"])
        for s in ctx["sections"]:
            lines += ["", s["text"]["headline"].upper(), *s["text"]["paragraphs"]]
        return "\n".join(lines)
