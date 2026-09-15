"""
The Wednesday catchment edition: who each club is fighting for.

One theme across every club in tiers 1 to 5, rotating weekly, and one
club profiled in depth - the club whose market and level disagree most,
that has not been profiled before. The rotation state is the archive:
each edition's claims.json records the club it profiled.

Everything here reads club_catchment, which src/catchment.py builds
with a gravity model over MSOA population - modelled, not counted. The
site's team page uses the same vocabulary, and this edition should not
invent a second one: "people it can draw on", "restored to its ceiling",
"contested" for the share of a club's nearest population that goes
elsewhere.

The facts layer. Words are in templates/email/catchment.html and
editions/phrasing.py.
"""

import datetime
import logging
import math
import sqlite3
from pathlib import Path

import charts
import digest
import fixtures as fixtures_mod
from editions import archive, config, phrasing, render
from editions.base import Edition, EditionOutput
from editions.preview import TIER_NAMES

logger = logging.getLogger(__name__)

THEMES = ("contested", "market", "overachievers", "restored", "deserts")
THEME_ROWS = 10
SCOPE_TIERS = (1, 2, 3, 4, 5)

# A desert is population further than this from any club in scope.
DESERT_MILES = 20.0

# The demographics are English MSOAs only (docs/catchment-data.md), so a
# Welsh club's catchment is whatever sliver of England lies within reach -
# Swansea's is north Devon, across the Bristol Channel. Ranking them or
# profiling them on that number would be a false story. They stay in the
# deserts calculation, because they are real grounds people travel to.
OUTSIDE_ENGLAND = {"cardiff-city-fc", "swansea-city-fc", "newport-county-fc", "wrexham-fc"}

# Income is mentioned only at the extremes: the whole range is narrow
# enough that the middle carries no story (docs/editions.md §4).
INCOME_EXTREME_PCT = 5.0


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def clubs_in_scope(conn: sqlite3.Connection, season: int) -> list[dict]:
    """Every club in tiers 1-5 with a catchment row, ranked by market and by level."""
    if not _table_exists(conn, "club_catchment"):
        return []
    has_traj = _table_exists(conn, "club_trajectory")
    rows = conn.execute(
        f"""
        SELECT cc.club_id, cm.canonical_name, cm.current_tier, cm.stadium_name,
               cm.latitude, cm.longitude,
               cc.catchment_pop_current, cc.catchment_pop_restored, cc.catchment_income,
               cc.voronoi_pop, cc.contest_ratio,
               cc.nearest_rival_id, cc.nearest_rival_miles, cc.nearest_rival_tier,
               s.position,
               {"t.highest_tier" if has_traj else "NULL"}
        FROM club_catchment cc
        JOIN club_master cm ON cm.club_id = cc.club_id
        LEFT JOIN standings s ON s.club_id = cc.club_id AND s.season_end_year = ?
        {"LEFT JOIN club_trajectory t ON t.club_id = cc.club_id" if has_traj else ""}
        WHERE cm.current_tier BETWEEN 1 AND 5
        """,
        (season,),
    ).fetchall()
    keys = ["club_id", "name", "tier", "stadium", "lat", "lon", "pop", "restored", "income",
            "voronoi", "contest", "rival_id", "rival_miles", "rival_tier", "position",
            "highest_tier"]
    clubs = [dict(zip(keys, r)) for r in rows]
    for c in clubs:
        c["division"] = TIER_NAMES.get(c["tier"], f"Tier {c['tier']}")
        c["outside_england"] = c["club_id"] in OUTSIDE_ENGLAND
    clubs = [c for c in clubs if not c["outside_england"]] + [c for c in clubs if c["outside_england"]]

    ranked = [c for c in clubs if not c["outside_england"]]
    by_pop = sorted(ranked, key=lambda c: -(c["pop"] or 0))
    for n, c in enumerate(by_pop, start=1):
        c["pop_rank"] = n
    by_level = sorted(ranked, key=lambda c: (c["tier"], c["position"] or 99))
    for n, c in enumerate(by_level, start=1):
        c["ladder_rank"] = n
    with_income = sorted((c for c in ranked if c["income"]), key=lambda c: -c["income"])
    for n, c in enumerate(with_income, start=1):
        c["income_rank"] = n
        c["income_pct"] = 100.0 * (n - 0.5) / len(with_income)   # 0 = richest
    return clubs


# ── Themes ─────────────────────────────────────────────────────────────────

def theme_contested(clubs: list[dict], names: dict) -> list[dict]:
    rows = sorted((c for c in clubs if c["contest"] is not None), key=lambda c: -c["contest"])
    return [{
        "name": c["name"], "division": c["division"],
        "rival": names.get(c["rival_id"], c["rival_id"] or ""),
        "rival_division": TIER_NAMES.get(c["rival_tier"], f"tier {c['rival_tier']}") if c["rival_tier"] else "",
        "miles": c["rival_miles"], "contested": round(100 * c["contest"]),
        "people": c["pop"],
    } for c in rows[:THEME_ROWS]]


def theme_market(clubs: list[dict]) -> list[dict]:
    """The biggest markets in the lower divisions."""
    rows = sorted((c for c in clubs if c["tier"] >= 3), key=lambda c: -(c["pop"] or 0))
    return [{"name": c["name"], "division": c["division"], "people": c["pop"],
             "pop_rank": c["pop_rank"], "ladder_rank": c["ladder_rank"]}
            for c in rows[:THEME_ROWS]]


def theme_overachievers(clubs: list[dict]) -> list[dict]:
    """The smallest markets in the top two divisions."""
    rows = sorted((c for c in clubs if c["tier"] <= 2), key=lambda c: (c["pop"] or 0))
    return [{"name": c["name"], "division": c["division"], "people": c["pop"],
             "pop_rank": c["pop_rank"], "ladder_rank": c["ladder_rank"]}
            for c in rows[:THEME_ROWS]]


def theme_restored(clubs: list[dict]) -> list[dict]:
    """Who would draw most more people back at their historical ceiling."""
    rows = [c for c in clubs if c["pop"] and c["restored"] and c["restored"] > c["pop"]]
    rows.sort(key=lambda c: -(c["restored"] / c["pop"]))
    return [{"name": c["name"], "division": c["division"],
             "ceiling": TIER_NAMES.get(c["highest_tier"], "") if c["highest_tier"] else "",
             "people": c["pop"], "restored": c["restored"],
             "multiple": round(c["restored"] / c["pop"], 1)}
            for c in rows[:THEME_ROWS]]


def _haversine_miles(lat1, lon1, lat2, lon2):
    import numpy as np
    r = 3958.8
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def theme_deserts(conn: sqlite3.Connection, clubs: list[dict]) -> list[dict]:
    """
    Local authorities with the most people further than DESERT_MILES from
    any club in tiers 1-5. Straight-line distance from each MSOA's
    population-weighted centroid.
    """
    if not _table_exists(conn, "msoa_demographics"):
        return []
    import numpy as np
    sited = [c for c in clubs if c["lat"] is not None and c["lon"] is not None]
    if not sited:
        return []
    msoas = conn.execute(
        "SELECT local_authority, latitude, longitude, population FROM msoa_demographics"
        " WHERE latitude IS NOT NULL AND population IS NOT NULL").fetchall()
    if not msoas:
        return []
    la = np.array([m[0] or "" for m in msoas])
    mlat = np.array([m[1] for m in msoas], dtype=float)
    mlon = np.array([m[2] for m in msoas], dtype=float)
    pop = np.array([m[3] for m in msoas], dtype=float)
    clat = np.array([c["lat"] for c in sited], dtype=float)
    clon = np.array([c["lon"] for c in sited], dtype=float)
    d = _haversine_miles(mlat[:, None], mlon[:, None], clat[None, :], clon[None, :])
    nearest_idx = d.argmin(axis=1)
    nearest = d[np.arange(len(msoas)), nearest_idx]
    far = nearest > DESERT_MILES
    out = []
    for name in sorted(set(la[far])):
        mask = (la == name)
        far_mask = mask & far
        i = int(np.argmax(np.where(far_mask, nearest, -1)))
        out.append({
            "authority": name,
            "people_far": int(pop[far_mask].sum()),
            "people": int(pop[mask].sum()),
            "furthest_miles": round(float(nearest[i]), 1),
            "nearest_club": sited[int(nearest_idx[i])]["name"],
        })
    out.sort(key=lambda r: -r["people_far"])
    return out[:THEME_ROWS]


# ── The profile ────────────────────────────────────────────────────────────

def profile_score(c: dict, n: int, median_contest: float) -> float:
    """How far market and level disagree, plus how unusual the contest is."""
    if not c.get("pop") or not c.get("ladder_rank"):
        return 0.0
    mismatch = abs(c["pop_rank"] - c["ladder_rank"]) / max(n, 1)
    contest = abs((c["contest"] or median_contest) - median_contest)
    return mismatch + contest


def already_profiled() -> set[str]:
    return {doc["claims"][0]["profile"] for doc in archive.all_claims("catchment")
            if doc.get("claims") and doc["claims"][0].get("profile")}


def choose_profile(clubs: list[dict]) -> dict | None:
    if not clubs:
        return None
    contests = sorted(c["contest"] for c in clubs if c["contest"] is not None)
    median = contests[len(contests) // 2] if contests else 0.0
    done = already_profiled()
    candidates = [c for c in clubs if c["club_id"] not in done] or clubs
    return max(candidates, key=lambda c: (profile_score(c, len(clubs), median), c["name"]))


class CatchmentEdition(Edition):
    name = "catchment"

    def build(self, theme: str | None = None, profile_id: str | None = None) -> EditionOutput:
        conn, date = self.conn, self.date
        season = fixtures_mod.current_season_end_year(date)
        names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))
        all_clubs = clubs_in_scope(conn, season)
        clubs = [c for c in all_clubs if not c["outside_england"]]
        kind = theme or THEMES[date.isocalendar()[1] % len(THEMES)]

        if kind == "contested":
            rows = theme_contested(clubs, names)
        elif kind == "market":
            rows = theme_market(clubs)
        elif kind == "overachievers":
            rows = theme_overachievers(clubs)
        elif kind == "restored":
            rows = theme_restored(clubs)
        else:
            rows = theme_deserts(conn, all_clubs)

        profile = None
        if profile_id:
            profile = next((c for c in clubs if c["club_id"] == profile_id), None)
        if profile is None:
            profile = choose_profile(clubs)

        images: list[tuple[Path, str]] = []
        if profile:
            profile["rival"] = names.get(profile["rival_id"], profile["rival_id"] or "")
            profile["rival_division"] = (TIER_NAMES.get(profile["rival_tier"], f"tier {profile['rival_tier']}")
                                         if profile["rival_tier"] else "")
            profile["ceiling"] = TIER_NAMES.get(profile["highest_tier"], "") if profile["highest_tier"] else ""
            profile["income_extreme"] = (
                profile.get("income_pct") is not None
                and (profile["income_pct"] <= INCOME_EXTREME_PCT
                     or profile["income_pct"] >= 100 - INCOME_EXTREME_PCT))
            ctx = digest.club_context(conn, profile["club_id"])
            profile["level_sentence"] = phrasing._level_sentence(ctx) if ctx else None
            profile["paragraphs"] = phrasing.profile_paragraphs(profile, len(clubs))
            path = charts.fixture_chart(conn, profile["club_id"], None, profile["name"], "",
                                        self.chart_dir / "profile.png",
                                        show_tier_lines=True, show_events=True, color_by_tier=True)
            if path:
                profile["cid"] = "profile"
                images.append((path, "profile"))

        thin = None
        if not clubs:
            thin = phrasing.thin_catchment()

        ctx = {
            "date": date, "theme": kind, "theme_title": phrasing.theme_title(kind),
            "theme_intro": phrasing.theme_intro(kind, len(clubs)),
            "rows": rows, "profile": profile, "club_count": len(clubs), "thin": thin,
            "desert_miles": int(DESERT_MILES),
            "archive_url": config.archive_url(self.name, date.isoformat()),
            "site_url": config.SITE_URL,
        }
        subject = phrasing.catchment_subject(ctx)
        html = render.render("catchment.html", **ctx)
        claims = [{"theme": kind, "profile": profile["club_id"] if profile else None}]
        return EditionOutput(subject=subject, html=html, text=self._text(ctx),
                             images=images, claims=claims, thin=thin)

    @staticmethod
    def _text(ctx: dict) -> str:
        lines = [f"CATCHMENT - {ctx['theme_title']}", "", ctx["theme_intro"], ""]
        if ctx["thin"]:
            lines.append(ctx["thin"])
        for r in ctx["rows"]:
            lines.append("  " + " | ".join(str(v) for v in r.values()))
        p = ctx["profile"]
        if p:
            lines += ["", f"PROFILE: {p['name'].upper()}"] + p["paragraphs"]
        return "\n".join(lines)
