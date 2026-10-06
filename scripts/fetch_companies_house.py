#!/usr/bin/env python3
"""
Fetch what Companies House holds about every club in tiers 1-7, and
settle the club-to-company matches the name scorer could not.

Runs in GitHub Actions (.github/workflows/companies-house.yml), reading
the API key from the CH_API_KEY repository secret. The key is sent only
to api.company-information.service.gov.uk, never printed and never
written to a file. Writes one file, data/companies_house.json.

TWO STAGES.

1. Match. data/club-companies.tsv holds a reviewed company for 178 clubs.
   For the rest - 67 marked `review`, 6 `not_found` - the name searches
   are run again (the same queries scripts/find_club_companies.py builds,
   scored by its rank()), and the register is asked for evidence the name
   cannot give, candidate by candidate:
     - its registered office is within 15 miles of the club's ground
       (postcodes.io, no key, for the coordinates);
     - a charge on it names the club's ground;
     - a director or person with significant control matches the owner
       the club's facts name;
     - it is the subsidiary of another candidate - the operating club
       under a holding company - so it is taken and its parent recorded.
   A candidate is matched automatically only with at least one of those
   and a clear lead over the next. Everything else stays unmatched and
   the page lists it, because a wrong match is worse than none.

2. Snapshot. For every matched club: the company profile (status,
   accounts due and overdue, last accounts type), officers, persons with
   significant control - followed up to three companies when the
   controller is itself a UK company - charges, insolvency cases and the
   last ten accounts filings. Trimmed to what the site uses.

About 3,000 requests at the published limit of 600 per five minutes:
roughly half an hour.
"""

import argparse
import base64
import datetime
import json
import math
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import find_club_companies as fcc  # noqa: E402

API = "https://api.company-information.service.gov.uk"
POSTCODES = "https://api.postcodes.io/postcodes"
DELAY = 0.52            # 600 requests per 300 seconds, with room for retries
NEAR_MILES = 15
FAR_MILES = 40
AUTO_MIN_SCORE = 90
AUTO_MIN_MARGIN = 25
UK = {"england", "wales", "scotland", "northern ireland", "united kingdom", "england and wales", "uk",
      "great britain", "england & wales"}


class Register:
    """A polite Companies House client: basic auth, a steady pace, retries."""

    def __init__(self, key: str, session=None, delay: float = DELAY):
        self.s = session or requests.Session()
        token = base64.b64encode(f"{key}:".encode()).decode()
        self.s.headers.update({"Authorization": f"Basic {token}",
                               "User-Agent": "english-ftbl26 (github.com/petedilworth/english-ftbl26)"})
        self.delay = delay
        self.calls = 0
        self._last = 0.0

    def get(self, path: str, **params):
        for attempt in range(6):
            wait = self._last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.calls += 1
            try:
                r = self.s.get(API + path, params=params, timeout=30)
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            if r.status_code in (401, 403):
                raise SystemExit(f"Companies House refused the key (HTTP {r.status_code}). Check the CH_API_KEY secret.")
            time.sleep(min(60, 2 ** attempt * (5 if r.status_code == 429 else 1)))
        print(f"  gave up on {path}", file=sys.stderr)
        return None

    def items(self, path: str, limit: int = 300, **params) -> list:
        out, start = [], 0
        while len(out) < limit:
            page = self.get(path, items_per_page=100, start_index=start, **params)
            got = (page or {}).get("items") or []
            out += got
            total = (page or {}).get("total_results") or (page or {}).get("total_count") or 0
            if not got or len(out) >= total:
                break
            start += len(got)
        return out[:limit]


# ── matching ──────────────────────────────────────────────────────────────

def search(reg: Register, query: str) -> list:
    kind, term = query.split(":", 1)
    if kind == "plain":
        page = reg.get("/search/companies", q=term, items_per_page=30)
    elif kind == "adv":
        page = reg.get("/advanced-search/companies", company_name_includes=term, size=100)
    elif kind == "sic":
        page = reg.get("/advanced-search/companies", company_name_includes=term, sic_codes="93120", size=100)
    else:
        return []
    return (page or {}).get("items") or []


def miles(a, b) -> float | None:
    if not a or not b or None in a or None in b:
        return None
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    d = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(d))


def postcode_coords(postcodes: list[str], session=None) -> dict[str, tuple]:
    """Postcode -> (lat, lon) from postcodes.io, a hundred at a time."""
    s = session or requests.Session()
    out = {}
    clean = sorted({p.strip().upper() for p in postcodes if p})
    for i in range(0, len(clean), 100):
        try:
            r = s.post(POSTCODES, json={"postcodes": clean[i:i + 100]}, timeout=30)
            for res in (r.json().get("result") or []):
                hit = res.get("result")
                if hit:
                    out[res["query"].strip().upper()] = (hit["latitude"], hit["longitude"])
        except (requests.RequestException, ValueError):
            continue
    return out


def _words(text: str) -> set[str]:
    stop = {"limited", "ltd", "plc", "the", "and", "of", "fc", "football", "club", "group", "holdings", "company",
            "mr", "mrs", "ms", "sir", "dr", "a", "an", "inc", "llc", "uk"}
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in stop}


def evidence(ev: dict, club: dict, office: tuple | None, others: set[str]) -> tuple[int, list[str], str | None]:
    """Extra points from the register for one candidate, the reasons, and its parent if another candidate."""
    points, why, parent = 0, [], None
    d = miles(office, club.get("coords"))
    if d is not None:
        if d <= NEAR_MILES:
            points += 40; why.append(f"registered office {d:.0f} miles from the ground")
        elif d >= FAR_MILES:
            points -= 25; why.append(f"registered office {d:.0f} miles away")
    ground = _words(club.get("ground") or "")
    for c in ev.get("charges") or []:
        text = " ".join([(c.get("particulars") or {}).get("description") or "",
                         (c.get("classification") or {}).get("description") or ""])
        if ground and len(ground & _words(text)) >= max(1, len(ground) // 2):
            points += 60; why.append("a charge names the ground"); break
    owner = _words(club.get("owner") or "")
    if owner:
        people = [p.get("name", "") for p in ev.get("psc") or []] + [o.get("name", "") for o in ev.get("officers") or []
                                                                     if not o.get("resigned_on")]
        if any(len(owner & _words(p)) >= min(2, len(owner)) for p in people):
            points += 50; why.append("a director or controller matches the club's owner")
    for p in ev.get("psc") or []:
        reg_no = ((p.get("identification") or {}).get("registration_number") or "").upper().lstrip("0")
        if reg_no and reg_no in others:
            points += 30; why.append("subsidiary of another candidate"); parent = reg_no; break
    last = (((ev.get("profile") or {}).get("accounts") or {}).get("last_accounts") or {}).get("type")
    if last == "dormant":
        points -= 30; why.append("files dormant accounts")
    return points, why, parent


def gather(reg: Register, number: str) -> dict:
    """Profile, officers, PSCs and charges for one company: enough to judge it."""
    return {"profile": reg.get(f"/company/{number}") or {},
            "officers": reg.items(f"/company/{number}/officers", limit=200),
            "psc": reg.items(f"/company/{number}/persons-with-significant-control", limit=50),
            "charges": reg.items(f"/company/{number}/charges", limit=200)}


FOOTBALL_WORDS = re.compile(r"\b(football|f\.?\s?c\.?|a\.?f\.?c\.?|soccer|association football)\b", re.I)


def footballish(name: str) -> bool:
    """Whether a company's name says it is a football club."""
    return bool(FOOTBALL_WORDS.search(name or ""))


def decide(club: dict, scored: list[dict], evid: dict[str, dict], offices: dict[str, tuple]) -> dict:
    """Name score plus register evidence; auto-match only with evidence and a clear lead."""
    others = {c["company_number"].upper().lstrip("0") for c in scored}
    rows = []
    for c in scored:
        num = c["company_number"]
        ev = evid.get(num) or {}
        status = (ev.get("profile") or {}).get("company_status") or c.get("company_status")
        if status and status not in ("active", "open"):
            continue
        extra, why, parent = evidence(ev, club, offices.get(num), others - {num.upper().lstrip("0")})
        if "files dormant accounts" in why:
            continue          # a dormant company is not the club that plays
        strong = any(w.startswith(("a charge", "a director", "subsidiary")) for w in why)
        # Being near the ground is evidence only for a company whose name
        # says football: the first run matched a yacht club, a wrestling
        # club and a cycling club on nearness alone.
        near = any(w.startswith("registered office") and "from the ground" in w for w in why)
        rows.append({"number": num, "name": c["entity_name"], "name_score": c["score"], "score": c["score"] + extra,
                     "why": why, "parent": parent,
                     "has_evidence": strong or (near and footballish(c["entity_name"]))})
    rows.sort(key=lambda r: -r["score"])
    if not rows:
        return {"state": "unmatched", "why": "no active candidate"}
    def key(n):
        return n.upper().lstrip("0")

    best = rows[0]
    rest = rows[1:]
    # A holding company and the club company beneath it are one club, not
    # two rivals: take the operating company, and measure its lead against
    # the next candidate that is neither of them.
    if rest:
        a, b = rows[0], rows[1]
        if b["parent"] and b["parent"] == key(a["number"]):
            best, rest = b, rows[2:]
        elif a["parent"] and a["parent"] == key(b["number"]):
            best, rest = a, rows[2:]
    margin = best["score"] - (rest[0]["score"] if rest else 0)
    if best["score"] >= AUTO_MIN_SCORE and margin >= AUTO_MIN_MARGIN and best["has_evidence"]:
        return {"state": "auto", "number": best["number"], "name": best["name"],
                "why": "; ".join(best["why"]) + f" (score {best['score']}, lead {margin})"}
    return {"state": "unmatched", "why": f"best was {best['name']} at {best['score']}, lead {margin}"
            + (f": {'; '.join(best['why'])}" if best["why"] else ": no evidence on the register"),
            "candidates": [{"number": r["number"], "name": r["name"], "score": r["score"]} for r in rows[:3]]}


# ── the snapshot ──────────────────────────────────────────────────────────

def _psc(p: dict) -> dict:
    ident = p.get("identification") or {}
    return {"name": p.get("name"), "kind": (p.get("kind") or "").replace("-person-with-significant-control", ""),
            "natures": p.get("natures_of_control") or [], "notified": p.get("notified_on"), "ceased": p.get("ceased_on"),
            "nationality": p.get("nationality"), "residence": p.get("country_of_residence"),
            "country": ident.get("country_registered") or ident.get("place_registered"),
            "legal_form": ident.get("legal_form"), "number": ident.get("registration_number")}


UK_WORDS = re.compile(r"\b(united kingdom|u\.?k\.?|england|wales|scotland|northern ireland|great britain|"
                      r"companies house|cardiff|london)\b", re.I)


def is_uk(place: str | None) -> bool:
    """'England', 'United Kingdom (England)', 'U.K.', 'Companies House, Cardiff' - the register spells it many ways."""
    return bool(place) and bool(UK_WORDS.search(place))


def chain(reg: Register, pscs: list[dict], depth: int = 3) -> list[dict]:
    """Follow the active corporate controller up through UK companies, as far as three steps."""
    out, seen = [], set()
    current = pscs
    for _ in range(depth):
        corp = [p for p in current if not p.get("ceased") and p["kind"].startswith("corporate-entity")
                and p.get("number") and is_uk(p.get("country"))]
        if len(corp) != 1:
            break
        num = re.sub(r"\s", "", corp[0]["number"]).upper()
        num = num.zfill(8) if num.isdigit() else num
        if num in seen:
            break
        seen.add(num)
        profile = reg.get(f"/company/{num}") or {}
        above = [_psc(p) for p in reg.items(f"/company/{num}/persons-with-significant-control", limit=50)]
        out.append({"number": num, "name": profile.get("company_name") or corp[0]["name"],
                    "status": profile.get("company_status"), "psc": above})
        current = above
    return out


def snapshot(reg: Register, number: str, ev: dict | None = None) -> dict:
    ev = ev or gather(reg, number)
    p = ev.get("profile") or {}
    acc = p.get("accounts") or {}
    conf = p.get("confirmation_statement") or {}
    office = p.get("registered_office_address") or {}
    insolvency = (reg.get(f"/company/{number}/insolvency") or {}).get("cases") if p.get("has_insolvency_history") else []
    filings = reg.items(f"/company/{number}/filing-history", limit=10, category="accounts")
    pscs = [_psc(x) for x in ev.get("psc") or []]
    return {
        "number": number, "name": p.get("company_name"), "status": p.get("company_status"), "type": p.get("type"),
        "created": p.get("date_of_creation"), "sic": p.get("sic_codes") or [],
        "office": {"locality": office.get("locality"), "postcode": office.get("postal_code")},
        "accounts": {"last_made_up_to": (acc.get("last_accounts") or {}).get("made_up_to"),
                     "last_type": (acc.get("last_accounts") or {}).get("type"),
                     "next_due": acc.get("next_due"), "overdue": bool(acc.get("overdue"))},
        "confirmation": {"next_due": conf.get("next_due"), "overdue": bool(conf.get("overdue"))},
        "officers": [{"name": o.get("name"), "role": o.get("officer_role"), "appointed": o.get("appointed_on"),
                      "resigned": o.get("resigned_on"), "nationality": o.get("nationality"),
                      "residence": o.get("country_of_residence")} for o in ev.get("officers") or []],
        "psc": pscs,
        "chain": chain(reg, pscs),
        "charges": [{"status": c.get("status"), "created": c.get("created_on"), "satisfied": c.get("satisfied_on"),
                     "lenders": [x.get("name") for x in c.get("persons_entitled") or [] if x.get("name")],
                     "classification": (c.get("classification") or {}).get("description"),
                     "particulars": ((c.get("particulars") or {}).get("description") or "")[:300]}
                    for c in ev.get("charges") or []],
        "insolvency": [{"type": c.get("type"), "dates": [{"type": d.get("type"), "date": d.get("date")}
                                                         for d in c.get("dates") or []]} for c in insolvency or []],
        "filings": [{"date": f.get("date"), "type": f.get("type"),
                     "made_up_to": (f.get("description_values") or {}).get("made_up_date")} for f in filings],
    }


# ── the run ───────────────────────────────────────────────────────────────

def load_clubs(conn: sqlite3.Connection) -> dict[str, dict]:
    import csv

    import content

    loc = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT club_id, latitude, longitude FROM club_master")
           if r[1] is not None}
    out = {}
    for t in fcc.targets(conn):
        if t["tier"] == "":
            continue
        path = ROOT / "content" / f"{t['club_id']}.md"
        facts = (content.load_club(path) or {}).get("facts", {}) if path.exists() else {}
        ground = facts.get("stadium") or ((facts.get("ground") or {}).get("ground"))
        out[t["club_id"]] = dict(t, coords=loc.get(t["club_id"]), ground=ground, owner=facts.get("owner"))
    with (ROOT / "data" / "club-companies.tsv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if row["club_id"] in out:
                out[row["club_id"]]["reviewed"] = row
    return out


def run(reg: Register, conn: sqlite3.Connection, only: set[str] | None = None, pc_session=None) -> dict:
    clubs = load_clubs(conn)
    if only:
        clubs = {k: v for k, v in clubs.items() if k in only}
    result = {"fetched": datetime.date.today().isoformat(), "clubs": {}, "unmatched": {}}
    for i, (cid, club) in enumerate(sorted(clubs.items()), 1):
        row = club.get("reviewed") or {}
        try:
            if row.get("state") == "chosen" and row.get("company_number"):
                number = row["company_number"]
                result["clubs"][cid] = {"match": "reviewed", "why": row.get("why", ""),
                                        "company": snapshot(reg, number)}
            else:
                candidates = {}
                for q in club["queries"]:
                    for item in search(reg, q):
                        n = item.get("company_number")
                        if n and (n not in candidates or (item.get("sic_codes") and not candidates[n].get("sic_codes"))):
                            candidates[n] = item
                ranked = fcc.rank(club, list(candidates.values()))
                scored = ([ranked["chosen"]] if ranked["chosen"] else []) + ranked["runners_up"]
                evid = {c["company_number"]: gather(reg, c["company_number"]) for c in scored[:4]}
                offices = postcode_coords([((e.get("profile") or {}).get("registered_office_address") or {})
                                           .get("postal_code") for e in evid.values()], pc_session)
                office_of = {n: offices.get((((e.get("profile") or {}).get("registered_office_address") or {})
                                            .get("postal_code") or "").strip().upper()) for n, e in evid.items()}
                d = decide(club, scored[:4], evid, office_of)
                if d["state"] == "auto":
                    result["clubs"][cid] = {"match": "auto", "why": d["why"],
                                            "company": snapshot(reg, d["number"], evid.get(d["number"]))}
                else:
                    result["unmatched"][cid] = {"name": club["name"], "tier": club["tier"], "why": d["why"],
                                                "candidates": d.get("candidates", [])}
        except SystemExit:
            raise
        except Exception as exc:  # one club's odd record must not lose the other 250
            result["unmatched"][cid] = {"name": club["name"], "tier": club["tier"], "why": f"fetch failed: {exc}"}
        if i % 20 == 0:
            print(f"{i}/{len(clubs)} clubs, {reg.calls} requests", flush=True)
    result["requests"] = reg.calls
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch Companies House data for every club in tiers 1-7.")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "companies_house.json")
    ap.add_argument("--clubs", help="comma-separated club ids, for a trial run")
    args = ap.parse_args()
    key = os.environ.get("CH_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set the CH_API_KEY secret (Settings > Secrets and variables > Actions).")
    conn = sqlite3.connect(ROOT / "data" / "db" / "england.db")
    res = run(Register(key), conn, set(args.clubs.split(",")) if args.clubs else None)
    args.out.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    m = res["clubs"].values()
    print(f"{len(res['clubs'])} clubs matched ({sum(1 for c in m if c['match'] == 'reviewed')} reviewed, "
          f"{sum(1 for c in m if c['match'] == 'auto')} automatic), {len(res['unmatched'])} unmatched, "
          f"{res['requests']} requests")


if __name__ == "__main__":
    main()
