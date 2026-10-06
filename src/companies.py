"""
Behind the club: what Companies House says about the company each club
plays as - who controls it, what is borrowed against it, who runs it, and
whether its paperwork is in order.

The source is data/companies_house.json, written monthly by
scripts/fetch_companies_house.py. Everything here is read from the
register; nothing is modelled. Where the register is silent - a club that
is a community benefit society, or one whose company could not be matched
with evidence - the club is listed as not covered rather than guessed at.

A note on "control". The register names persons with significant control:
anyone holding more than a quarter of the shares or votes, or able to
appoint the board. When that person is itself a UK company, the fetch
follows it up to three steps, so the controller shown is the furthest one
the register reaches. A chain that ends at a company registered abroad
ends there: the register does not look past the border, and neither can
this page.
"""

import datetime
import json
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
SOURCE = PROJECT_ROOT / "data" / "companies_house.json"
UK = {"england", "wales", "scotland", "northern ireland", "united kingdom", "england and wales", "uk",
      "great britain", "england & wales", "british"}
CHURN_YEARS = 5

SHARE_BANDS = [("75-to-100", "75–100%"), ("50-to-75", "50–75%"), ("25-to-50", "25–50%")]


def load(path: Path = SOURCE) -> dict | None:
    if not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError:
        logger.warning("companies_house.json is not valid JSON")
        return None


UK_WORDS = re.compile(r"\b(united kingdom|u\.?k\.?|england|wales|scotland|northern ireland|great britain|"
                      r"british|english|welsh|scottish|companies house|cardiff|london)\b", re.I)
UK_FORMS = re.compile(r"\b(limited|ltd\.?|plc|llp|cic|community interest company)\s*$", re.I)


def _is_uk(place) -> bool:
    """The register spells the UK many ways: 'England', 'United Kingdom (England)', 'U.K.', 'British'."""
    return bool(place) and bool(UK_WORDS.search(str(place)))


def _band(natures: list[str]) -> str | None:
    for key, label in SHARE_BANDS:
        if any(key in n for n in natures):
            return label
    if any("right-to-appoint" in n for n in natures):
        return "appoints the board"
    if any("significant-influence" in n for n in natures):
        return "significant influence"
    return None


def _rank(natures: list[str]) -> int:
    """0 for the biggest share band, higher for smaller ones, 9 for none."""
    for i, (key, _label) in enumerate(SHARE_BANDS):
        if any(key in n for n in natures):
            return i
    return 9


def controller(company: dict) -> dict:
    """
    The furthest controller the register reaches, and what kind it is:
    a person (UK or abroad), a company abroad, or nobody with control.
    """
    levels = [company.get("psc") or []] + [c.get("psc") or [] for c in company.get("chain") or []]
    names = [company.get("name")] + [c.get("name") for c in company.get("chain") or []]
    for depth in range(len(levels) - 1, -1, -1):
        active = [p for p in levels[depth] if not p.get("ceased") and "statement" not in (p.get("kind") or "")]
        if not active:
            continue
        # The largest holder first; individuals before companies when tied.
        active.sort(key=lambda p: (_rank(p.get("natures") or []),
                                   0 if (p.get("kind") or "").startswith("individual") else 1))
        p = active[0]
        kind = p.get("kind") or ""
        if kind.startswith("individual"):
            where = p.get("residence") or p.get("nationality")
            category = "person in the UK" if _is_uk(where) else "person abroad"
        elif kind.startswith(("corporate-entity", "legal-person")):
            where = p.get("country")
            name = p.get("name") or ""
            if re.search(r"\bcouncil\b", name, re.I) or kind.startswith("legal-person"):
                category = "council or public body" if re.search(r"council|authority", name, re.I) else (
                    "company in the UK" if _is_uk(where) else "company abroad")
            elif where:
                category = "company in the UK" if _is_uk(where) else "company abroad"
            else:
                # No country given: a name ending Limited or PLC is a UK form; anything else is not stated.
                category = "company in the UK" if UK_FORMS.search(name) else "company, country not stated"
        else:
            where, category = None, "other"
        return {"name": p.get("name"), "category": category, "where": where, "band": _band(p.get("natures") or []),
                "steps": depth, "via": names[1:depth + 1], "others": len(active) - 1}
    return {"name": None, "category": "no single controller", "where": None, "band": None, "steps": 0,
            "via": [], "others": 0}


def charges(company: dict) -> dict:
    """Outstanding secured lending: how many, to whom, the newest, and whether any names a ground."""
    items = company.get("charges") or []
    out = [c for c in items if (c.get("status") or "").startswith(("outstanding", "part"))]
    lenders = []
    for c in out:
        for name in c.get("lenders") or []:
            if name not in lenders:
                lenders.append(name)
    text = " ".join(((c.get("particulars") or "") + " " + (c.get("classification") or "")).lower() for c in out)
    property_words = ("stadium", "ground", "freehold", "leasehold", "land", "park", "road")
    return {"outstanding": len(out), "satisfied": sum(1 for c in items if (c.get("status") or "") == "fully-satisfied"),
            "total": len(items), "lenders": lenders,
            "latest": max((c.get("created") or "" for c in out), default="") or None,
            "property": any(w in text for w in property_words)}


def directors(company: dict, today: datetime.date | None = None) -> dict:
    """Directors now, appointments and resignations in the last five years, and how many live abroad."""
    today = today or datetime.date.today()
    since = (today - datetime.timedelta(days=365 * CHURN_YEARS)).isoformat()
    people = [o for o in company.get("officers") or [] if "director" in (o.get("role") or "")]
    now = [o for o in people if not o.get("resigned")]
    gone = [o for o in people if (o.get("resigned") or "") >= since]
    came = [o for o in people if (o.get("appointed") or "") >= since]
    abroad = [o for o in now if o.get("residence") and not _is_uk(o.get("residence"))]
    longest = min((o.get("appointed") or "9999" for o in now), default=None)
    return {"now": len(now), "appointed": len(came), "resigned": len(gone), "abroad": len(abroad),
            "churn": round((len(came) + len(gone)) / CHURN_YEARS, 1),
            "longest_since": longest if longest and longest != "9999" else None}


def warnings(company: dict) -> list[str]:
    """Plain flags from the register: what a buyer or a fan would want to know first."""
    out = []
    acc = company.get("accounts") or {}
    if acc.get("overdue"):
        out.append("accounts overdue")
    if (company.get("confirmation") or {}).get("overdue"):
        out.append("confirmation statement overdue")
    if company.get("insolvency"):
        out.append("insolvency history")
    if (company.get("status") or "active") not in ("active", "open"):
        out.append(f"company {company.get('status')}")
    if acc.get("last_type") in ("micro-entity", "dormant"):
        out.append(f"files {acc['last_type']} accounts")
    return out


FOOTBALL_WORDS = re.compile(r"\b(football|f\.?\s?c\.?|a\.?f\.?c\.?|soccer|association football)\b", re.I)


def trusted(entry: dict) -> bool:
    """
    The same rule the fetch now applies, at read time, so a snapshot taken
    under the older rule cannot slip a wrong match through: an automatic
    match needs strong evidence, or nearness plus a football name, and is
    never a dormant company.
    """
    if entry.get("match") != "auto":
        return True
    why = entry.get("why") or ""
    name = (entry.get("company") or {}).get("name") or ""
    if "dormant" in why or ((entry.get("company") or {}).get("accounts") or {}).get("last_type") == "dormant":
        return False
    strong = any(k in why for k in ("a charge names the ground", "matches the club's owner", "subsidiary of another"))
    return strong or ("from the ground" in why and bool(FOOTBALL_WORDS.search(name)))


def assemble(conn, path: Path = SOURCE) -> dict:
    """Everything the page draws; {} without the snapshot."""
    data = load(path)
    if not data or not data.get("clubs"):
        return {}
    newest = conn.execute("SELECT MAX(season_end_year) FROM standings").fetchone()[0]
    tier = dict(conn.execute("SELECT club_id, tier FROM standings WHERE season_end_year = ? AND club_id IS NOT NULL",
                             (newest,)))
    names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))
    clubs = []
    dropped = {}
    for cid, entry in data["clubs"].items():
        co = entry.get("company") or {}
        if not co:
            continue
        if not trusted(entry):
            dropped[cid] = {"name": names.get(cid, cid), "tier": tier.get(cid),
                            "why": f"automatic match to {co.get('name')} not trusted: {entry.get('why')}"}
            continue
        ctl = controller(co)
        ch = charges(co)
        dr = directors(co)
        clubs.append({
            "club_id": cid, "name": names.get(cid, cid), "tier": tier.get(cid), "match": entry.get("match"),
            "company": co.get("name"), "number": co.get("number"), "status": co.get("status"),
            "created": co.get("created"), "last_accounts": (co.get("accounts") or {}).get("last_type"),
            "accounts_to": (co.get("accounts") or {}).get("last_made_up_to"),
            "controller": ctl, "charges": ch, "directors": dr, "warnings": warnings(co),
            "insolvency": co.get("insolvency") or [],
        })
    clubs.sort(key=lambda c: (c["tier"] or 99, c["name"]))
    categories = {}
    for c in clubs:
        categories.setdefault(c["controller"]["category"], []).append(c)
    unmatched = [{"club_id": k, "name": names.get(k, v.get("name")), "tier": v.get("tier"), "why": v.get("why")}
                 for k, v in list((data.get("unmatched") or {}).items()) + list(dropped.items())]
    unmatched.sort(key=lambda c: (c["tier"] or 99, c["name"] or ""))
    with_debt = [c for c in clubs if c["charges"]["outstanding"]]
    lenders = {}
    for c in with_debt:
        for name in c["charges"]["lenders"]:
            lenders.setdefault(name, []).append(c["name"])
    return {
        "fetched": data.get("fetched"),
        "clubs": clubs,
        "unmatched": unmatched,
        "categories": {k: len(v) for k, v in categories.items()},
        "abroad": [c for c in clubs if c["controller"]["category"] in ("person abroad", "company abroad",
                                                                         "company, country not stated")],
        "with_debt": sorted(with_debt, key=lambda c: (-c["charges"]["outstanding"], c["tier"] or 99)),
        "property_debt": [c for c in with_debt if c["charges"]["property"]],
        "lenders": sorted(([k, v] for k, v in lenders.items() if len(v) > 1), key=lambda kv: -len(kv[1])),
        "churn": sorted(clubs, key=lambda c: -c["directors"]["churn"])[:20],
        "warned": [c for c in clubs if c["warnings"]],
        "insolvent": [c for c in clubs if c["insolvency"]],
        "matched": {"reviewed": sum(1 for c in clubs if c["match"] == "reviewed"),
                    "auto": sum(1 for c in clubs if c["match"] == "auto")},
    }
