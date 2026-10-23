#!/usr/bin/env python3
"""
Measure how closely each club story follows the club's Wikipedia article.

WHY. The club stories in content/ were researched in a session whose
record did not survive, so nothing says which pages they were written
from. Wikipedia is the likeliest, and its text is CC BY-SA: a story that
repeats its wording is under share-alike terms; one that follows its
facts closely has, in effect, a source that can be named. This script
finds out which, club by club.

WHAT IT MEASURES. The story is every sentence written for the club: the
prose sections and the longer free-text facts (rivalry notes, origin
notes, administration notes). The article is Wikipedia's plain text of
the club's page, fetched through the API. Both are cut into words, and:

  share_5   - the share of the story's five-word runs that also appear in
              the article. High means the story follows the article.
  share_8   - the same for eight-word runs: high means shared wording.
  longest   - the longest run of words the two have in common, and the
              passages of twelve words or more, which are copied text.

Wikipedia is refused at the sandbox's proxy but not from GitHub Actions,
so .github/workflows/wikipedia-check.yml runs this and commits
data/wikipedia-overlap.tsv.

    python3 scripts/check_wikipedia_overlap.py
    python3 scripts/check_wikipedia_overlap.py --club peterborough-united-fc
"""

import argparse
import csv
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import content                                          # noqa: E402
from list_club_articles import candidate_titles         # noqa: E402

DB = PROJECT_ROOT / "data" / "db" / "england.db"
CONTENT = PROJECT_ROOT / "content"
OUT = PROJECT_ROOT / "data" / "wikipedia-overlap.tsv"
API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "english-ftbl26/1.0 (https://github.com/petedilworth/english-ftbl26; story overlap check)"
COPIED = 12            # words in common in a row that count as copied text
FIELDS = ["club_id", "article", "url", "story_words", "share_5", "share_8", "longest", "passages"]

logger = logging.getLogger("check_wikipedia_overlap")


def annotate(level: str, message: str) -> None:
    """Said where it can be read from here: the run's annotations come back through the API."""
    logger.log(logging.WARNING if level == "warning" else logging.INFO, "%s", message)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level}::{message[:2000]}", flush=True)


# ── Words and runs ────────────────────────────────────────────────────────

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "–": " ", "—": " "})


def words(text: str) -> list[str]:
    """Lower-case words, apostrophes kept inside them, markup and punctuation gone."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text or "")      # markdown links: keep the words
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.translate(_APOSTROPHES).lower())


def grams(ws: list[str], n: int) -> set[tuple]:
    return {tuple(ws[i:i + n]) for i in range(len(ws) - n + 1)}


def share(story: list[str], article_grams: set[tuple], n: int) -> float:
    """The share of the story's n-word runs that the article also has."""
    mine = [tuple(story[i:i + n]) for i in range(len(story) - n + 1)]
    return round(sum(g in article_grams for g in mine) / len(mine), 3) if mine else 0.0


def common_runs(story: list[str], article: list[str], n: int = 8, minimum: int = COPIED) -> list[tuple[int, str]]:
    """
    Stretches of the story that appear word for word in the article,
    longest first: [(length in words, the words)]. Built from n-word
    runs, so a stretch is found once it is n words long; only those of
    at least `minimum` words are kept.
    """
    have = grams(article, n)
    hits = [tuple(story[i:i + n]) in have for i in range(len(story) - n + 1)]
    runs, i = [], 0
    while i < len(hits):
        if not hits[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(hits) and hits[j + 1]:
            j += 1
        length = j - i + n
        if length >= minimum:
            runs.append((length, " ".join(story[i:i + length])))
        i = j + 1
    return sorted(runs, key=lambda r: -r[0])


def longest_run(story: list[str], article: list[str]) -> int:
    """The longest run of words in common, however short."""
    best = 0
    for n in (24, 16, 12, 8, 5, 3):
        runs = common_runs(story, article, n=n, minimum=n)
        if runs:
            best = runs[0][0]
            break
    return best


# ── The story and the article ─────────────────────────────────────────────

def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def story_text(path: Path) -> str:
    """Every sentence written for the club: the prose and the longer free-text facts."""
    club = content.load_club(path)
    if not club:
        return ""
    parts = list(club["sections"].values()) + [club["extra"] or ""]
    facts = {k: v for k, v in club["facts"].items() if k not in ("sources",)}
    parts += [s for s in _strings(facts) if len(s.split()) >= 8 and not s.startswith("http")]
    return "\n".join(p for p in parts if p)


def _api(params: dict, get) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    return json.loads(get(f"{API}?{query}"))


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def is_club_article(text: str) -> bool:
    head = (text or "")[:2000].lower()
    return ("football club" in head or "football team" in head) and "may refer to" not in head


def fetch_extract(title: str, get) -> tuple[str, str] | None:
    """(title as Wikipedia has it, plain text) after redirects, or None for no such page."""
    data = _api({"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "titles": title}, get)
    pages = data.get("query", {}).get("pages") or []
    if not pages or pages[0].get("missing") or not pages[0].get("extract"):
        return None
    return pages[0]["title"], pages[0]["extract"]


def find_article(name: str, get) -> tuple[str, str] | None:
    """The club's article: the likely titles first, then Wikipedia's own search."""
    tried = []
    for title in candidate_titles(name):
        tried.append(title)
        found = fetch_extract(title, get)
        if found and is_club_article(found[1]):
            return found
    hits = _api({"action": "query", "list": "search", "srsearch": f"{name} football club", "srlimit": 3}, get)
    for hit in hits.get("query", {}).get("search") or []:
        if hit["title"] in tried:
            continue
        found = fetch_extract(hit["title"], get)
        if found and is_club_article(found[1]):
            return found
    return None


def check(club_id: str, name: str, story: str, get) -> dict:
    row = {k: "" for k in FIELDS}
    row["club_id"] = club_id
    mine = words(story)
    row["story_words"] = len(mine)
    found = find_article(name, get)
    if not found:
        return row
    title, text = found
    theirs = words(text)
    row["article"] = title
    row["url"] = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
    row["share_5"] = share(mine, grams(theirs, 5), 5)
    row["share_8"] = share(mine, grams(theirs, 8), 8)
    row["longest"] = longest_run(mine, theirs)
    row["passages"] = " | ".join(passage[:200] for _, passage in common_runs(mine, theirs)[:3])
    return row


def run(clubs: list[tuple[str, str, str]], get, out: Path, pause: float = 0.2) -> list[dict]:
    """clubs: [(club_id, name, story)]. Writes the TSV; returns its rows."""
    rows = []
    for club_id, name, story in clubs:
        try:
            rows.append(check(club_id, name, story, get))
        except Exception as exc:             # one club's failure is that club's, not the run's
            annotate("warning", f"{club_id}: {exc}")
            rows.append({**{k: "" for k in FIELDS}, "club_id": club_id})
        time.sleep(pause)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        fh.write("# How closely each club story follows its Wikipedia article. Written by\n")
        fh.write("# scripts/check_wikipedia_overlap.py; see its docstring for the measures.\n")
        writer = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--club", action="append", help="only this club_id (repeatable)")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    names = dict(sqlite3.connect(DB).execute("SELECT club_id, canonical_name FROM club_master"))
    clubs = []
    for path in sorted(CONTENT.glob("*.md")):
        if path.name == "README.md" or (args.club and path.stem not in args.club):
            continue
        story = story_text(path)
        if story.strip() and path.stem in names:
            clubs.append((path.stem, names[path.stem], story))
    rows = run(clubs, _http_get, Path(args.out))

    found = [r for r in rows if r["article"]]
    copied = [r for r in found if int(r["longest"] or 0) >= COPIED]
    close = [r for r in found if float(r["share_5"] or 0) >= 0.2]
    annotate("notice", f"{len(rows)} stories checked; {len(found)} articles found; {len(close)} follow their article "
                       f"closely (a fifth or more of five-word runs shared); {len(copied)} share a passage of "
                       f"{COPIED} words or more")
    missing = [r["club_id"] for r in rows if not r["article"]]
    if missing:
        annotate("notice", f"no article found for {len(missing)}: {', '.join(missing[:40])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
