"""
The Money page: clubs compared on what their accounts say.

Everything here is read from club_finances and the standings, so the page
can only say what the filings do. The shape of that is fixed by the law
rather than by the data collection: a large company files its profit and
loss account, a small one may withhold it, so turnover and wages stop at
about the third tier and the balance sheet carries on to the seventh. The
page is built on that shape - turnover and wages where they exist, the
balance sheet everywhere - and says where each figure stops.

A figure the parser doubts is never shown as if it were sound:
"does_not_balance" withholds the balance sheet altogether, and the
corrections (a sign restored, an OCR character fixed, a level taken from
the contents page) put a mark on the row.

assemble() returns {} when there is nothing to show.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import statistics
from pathlib import Path

import companies
import finances

# The figures the page reads. A database built before a column existed
# simply lacks it, so each is read only if present.
FIELDS = ["turnover", "staff_costs", "profit_before_tax", "net_assets", "cash",
          "creditors_within_year", "employees"]
ROW_FIELDS = ["club_id", "season_end_year", "company_number", "entity_name", "consolidation_level",
              "disclosure", "flags", "source_url", "accounts_type", "audited", "pnl_withheld"]

# A balance sheet whose parts do not add up is withheld whole: which of its
# figures is the wrong one cannot be told from the filing.
BALANCE_FIELDS = {"net_assets", "cash", "creditors_within_year"}

# A row whose figures were corrected on the way in, and what to say.
DOUBT_LABELS = {
    "sign_corrected": "a missing minus sign restored, because the balance sheet only adds up with it",
    "ocr_corrected": "a scanned figure corrected by one character, because the balance sheet only adds up with it",
    "level_from_contents": "read from a scan holding two balance sheets, told apart by the contents page",
    "ixbrl_ambiguous": "the filing tags more than one value for a figure; the consolidated one is used",
}

# What each club's latest accounts disclose, in the order the bars stack.
# Colours are the validated categorical order, light mode; grey is kept for
# no-data and never used as a category of its own.
DISCLOSURE_KEY = [
    ("full", "Full accounts", "#2a78d6"),
    ("withheld", "Profit and loss withheld (s444)", "#eda100"),
    ("small", "Small company, balance sheet only", "#1baf7a"),
    ("unread", "On the register, no figures read", "#eb6834"),
    ("unmatched", "Not matched to a company", "#c8ced6"),
]

# Ink for a count printed on each colour: the darker fills take white.
DISCLOSURE_INK = {"full": "#ffffff", "unread": "#ffffff"}


def _flags(value) -> list[str]:
    if not value:
        return []
    try:
        flags = json.loads(value)
    except (TypeError, ValueError):
        flags = [f.strip() for f in str(value).replace(";", ",").split(",")]
    return [str(f).split(":")[0] for f in flags if f]


def money(value: int | float | None) -> str:
    """£1.2bn, £345m, £12.3m, £850k, £900; a minus sign for a loss."""
    if value is None:
        return "–"
    sign = "−" if value < 0 else ""
    v = abs(value)
    if v >= 1e9:
        text = f"£{v / 1e9:.1f}bn"
    elif v >= 1e8:
        text = f"£{v / 1e6:.0f}m"
    elif v >= 1e6:
        text = f"£{v / 1e6:.1f}m"
    elif v >= 1e4:
        text = f"£{v / 1e3:.0f}k"
    elif v >= 1e3:
        text = f"£{v / 1e3:.1f}k"
    else:
        text = f"£{v:.0f}"
    return sign + text


def _median(values: list) -> float | None:
    return statistics.median(values) if values else None


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _read_rows(conn) -> list[dict]:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(club_finances)")}
    wanted = [c for c in ROW_FIELDS + FIELDS if c in cols]
    rows = []
    for values in conn.execute(f"SELECT {', '.join(wanted)} FROM club_finances"):
        r = dict.fromkeys(ROW_FIELDS + FIELDS)
        r.update(zip(wanted, values))
        rows.append(r)
    return rows


def _standings(conn) -> dict[tuple[str, int], dict]:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(standings)")}
    deducted = "points_deducted" if "points_deducted" in cols else "0"
    out = {}
    for club_id, season, tier, points, ded, played, division in conn.execute(
            f"SELECT club_id, season_end_year, tier, points, {deducted}, played, division_name"
            " FROM standings WHERE club_id IS NOT NULL AND tier <= 7"):
        out[(club_id, season)] = {"tier": tier, "points": points, "deducted": ded or 0,
                                  "played": played, "division": division}
    return out


def _prepare(r: dict, standing: dict | None, name: str) -> dict:
    """One accounts row as the page shows it: doubts applied, ratios worked out."""
    flags = _flags(r.get("flags"))
    r = dict(r, flags=flags, name=name)
    r["tier"] = standing["tier"] if standing else None
    r["unbalanced"] = "does_not_balance" in flags
    if r["unbalanced"]:
        for f in BALANCE_FIELDS:
            r[f] = None
    r["doubts"] = [DOUBT_LABELS[f] for f in DOUBT_LABELS if f in flags]
    turnover, wages = r.get("turnover"), r.get("staff_costs")
    r["wage_ratio"] = wages / turnover if turnover and wages and turnover > 0 else None
    r["group"] = r.get("consolidation_level") == "group"
    return r


def _category(row: dict | None, on_register: bool) -> str:
    if row is None or row["disclosure"] in (finances.DISCLOSURE_NOT_FILED, finances.DISCLOSURE_DISSOLVED):
        return "unread" if on_register or row is not None else "unmatched"
    if row["disclosure"] == finances.DISCLOSURE_FULL:
        return "full"
    if row.get("pnl_withheld") == "yes":
        return "withheld"
    return "small"


def _registered(filings_path: Path, companies_path: Path) -> set[str]:
    """Clubs matched to a company: with a filing indexed, or a trusted register match."""
    found = set()
    if filings_path.exists():
        with filings_path.open(newline="", encoding="utf-8") as fh:
            found |= {r["club_id"] for r in csv.DictReader(fh, delimiter="\t") if r.get("company_number")}
    data = companies.load(companies_path) or {}
    for cid, entry in (data.get("clubs") or {}).items():
        if entry.get("company") and companies.trusted(entry):
            found.add(cid)
    return found


def _same_entity(a: dict, b: dict) -> bool:
    """Two years compare only if they are the same company at the same level."""
    if (a.get("consolidation_level") or "") != (b.get("consolidation_level") or ""):
        return False
    if a.get("company_number") or b.get("company_number"):
        return a.get("company_number") == b.get("company_number")
    return bool(a.get("entity_name")) and a.get("entity_name") == b.get("entity_name")


def assemble(conn: sqlite3.Connection, filings_path: Path = finances.FILINGS_INDEX,
             companies_path: Path = companies.SOURCE) -> dict:
    if not {"club_finances", "standings"} <= _tables(conn):
        return {}
    names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master")) \
        if "club_master" in _tables(conn) else {}
    standings = _standings(conn)
    rows = [_prepare(r, standings.get((r["club_id"], r["season_end_year"])), names.get(r["club_id"], r["club_id"]))
            for r in _read_rows(conn)]
    if not rows:
        return {}

    by_club: dict[str, dict[int, dict]] = {}
    for r in rows:
        by_club.setdefault(r["club_id"], {})[r["season_end_year"]] = r

    def has_figures(r):
        return r["disclosure"] not in (finances.DISCLOSURE_NOT_FILED, finances.DISCLOSURE_DISSOLVED) \
            and any(r.get(f) is not None for f in FIELDS)

    latest = {}
    for cid, seasons in by_club.items():
        shown = [r for r in seasons.values() if has_figures(r)]
        if shown:
            latest[cid] = max(shown, key=lambda r: r["season_end_year"])

    # 1. The money league: each club's latest accounts, in the tier it played that season.
    league = {}
    for r in latest.values():
        if r["tier"]:
            league.setdefault(r["tier"], []).append(r)
    for t in league:
        key = "turnover" if t <= 3 else "net_assets"
        league[t].sort(key=lambda r: (r.get(key) is None, -(r.get(key) or 0), r["name"]))

    # 2. The cliff: medians per tier, with how many clubs each rests on.
    cliff = []
    for t in sorted(league):
        tv = [r["turnover"] for r in league[t] if r.get("turnover") is not None]
        na = [r["net_assets"] for r in league[t] if r.get("net_assets") is not None]
        wr = [r["wage_ratio"] for r in league[t] if r.get("wage_ratio") is not None]
        cliff.append({"tier": t, "clubs": len(league[t]),
                      "turnover": _median(tv), "turnover_n": len(tv),
                      "net_assets": _median(na), "net_assets_n": len(na),
                      "negative": sum(1 for v in na if v < 0),
                      "wage_ratio": _median(wr), "wage_ratio_n": len(wr)})

    # What a parachute is worth: second-tier clubs relegated from the top
    # flight within the three seasons before, against the rest.
    def came_down(r):
        y = r["season_end_year"]
        return any((standings.get((r["club_id"], y - k)) or {}).get("tier") == 1 for k in (1, 2, 3))
    second = [r for r in league.get(2, []) if r.get("turnover") is not None]
    parachute = None
    if second:
        down = [r["turnover"] for r in second if came_down(r)]
        rest = [r["turnover"] for r in second if not came_down(r)]
        if down and rest:
            parachute = {"down": _median(down), "down_n": len(down), "rest": _median(rest), "rest_n": len(rest)}

    # 3. Cost per point: wages over the points won on the pitch that season.
    cost = []
    for r in latest.values():
        s = standings.get((r["club_id"], r["season_end_year"]))
        if not s or s["tier"] > 3 or not r.get("staff_costs") or r["disclosure"] != finances.DISCLOSURE_FULL:
            continue
        won = (s["points"] or 0) + (s["deducted"] or 0)
        if won <= 0:
            continue
        cost.append(dict(r, points=won, deducted=s["deducted"], per_point=r["staff_costs"] / won))
    cost.sort(key=lambda r: -r["per_point"])
    cost_median = {t: _median([r["per_point"] for r in cost if r["tier"] == t]) for t in (1, 2, 3)}

    # 4. Movers: the same company, at the same level, a year apart.
    ratio_moves, asset_moves = [], []
    for cid, seasons in by_club.items():
        for y, now in seasons.items():
            before = seasons.get(y - 1)
            if not before or not _same_entity(before, now) or not (before["tier"] or now["tier"]):
                continue
            move = {"club_id": cid, "name": now["name"], "season_end_year": y,
                    "tier_before": before["tier"], "tier": now["tier"], "group": now["group"],
                    "source_url": now.get("source_url")}
            if before["wage_ratio"] is not None and now["wage_ratio"] is not None:
                ratio_moves.append(dict(move, before=before["wage_ratio"], after=now["wage_ratio"],
                                        change=now["wage_ratio"] - before["wage_ratio"]))
            if before.get("net_assets") is not None and now.get("net_assets") is not None:
                asset_moves.append(dict(move, before=before["net_assets"], after=now["net_assets"],
                                        change=now["net_assets"] - before["net_assets"],
                                        doubts=before["doubts"] + now["doubts"]))
    ratio_moves.sort(key=lambda m: -abs(m["change"]))
    asset_moves.sort(key=lambda m: m["change"])

    # 5. What each club discloses: every club in tiers 1-7 this season, by its latest accounts.
    newest = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    registered = _registered(filings_path, companies_path)
    current = [(cid, t) for cid, t in conn.execute(
        "SELECT club_id, tier FROM standings WHERE season_end_year = ? AND club_id IS NOT NULL AND tier <= 7"
        " ORDER BY tier", (newest,))]
    disclosure, every = {}, []
    for cid, t in current:
        seasons = by_club.get(cid, {})
        row = latest.get(cid) or (max(seasons.values(), key=lambda r: r["season_end_year"]) if seasons else None)
        cat = _category(row, cid in registered)
        disclosure.setdefault(t, dict.fromkeys((k for k, _, _ in DISCLOSURE_KEY), 0))[cat] += 1
        every.append({"club_id": cid, "name": names.get(cid, cid), "tier": t, "category": cat, "row": row})
    every.sort(key=lambda c: (c["tier"], [k for k, _, _ in DISCLOSURE_KEY].index(c["category"]), c["name"]))

    flagged = {f: sum(1 for r in latest.values() if f in r["flags"]) for f in ("does_not_balance", *DOUBT_LABELS)}
    return {
        "rows": rows, "latest": latest, "league": league, "cliff": cliff, "parachute": parachute,
        "cost": cost, "cost_median": cost_median,
        "ratio_moves": ratio_moves, "asset_moves": asset_moves,
        "disclosure": disclosure, "every": every, "newest": newest, "flagged": flagged,
    }
