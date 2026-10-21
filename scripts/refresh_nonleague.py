#!/usr/bin/env python3
"""
Refresh the sixth and seventh tiers' results for the season in progress.

The six divisions below the National League come from the results grids
in Wikipedia's season articles (scripts/parse_wiki_results.py explains
the format and why a grid beats a published table). Wikipedia is refused
at this sandbox's proxy but not from GitHub Actions, so the workflow in
.github/workflows/nonleague.yml runs this every morning before Refresh
ingests the day's results. Only the season in progress is fetched; the
seasons already complete stay as committed.

A grid is refused, and the committed file left alone, when it comes out
wrong rather than merely short: a club name this project cannot resolve,
a club list that differs from the committed one, fewer matches than are
already committed, a committed fixture that has vanished, a fixture
listed twice, or more matches than a round-robin holds. Each of those is
how a half-edited article or a changed template looks, and a table built
from it would be wrong in a way nothing downstream can see. A refused
division fails the run loudly; the divisions that passed are still
written, because one broken article should not freeze the other five.

    python3 scripts/refresh_nonleague.py            # the season in progress
    python3 scripts/refresh_nonleague.py --season 2027 --dry-run
"""

import argparse
import csv
import datetime
import logging
import re
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import entities                                         # noqa: E402
import historical                                       # noqa: E402
import parse_wiki_results as wiki                       # noqa: E402

OUT_DIR = PROJECT_ROOT / "data" / "nonleague"
DB = PROJECT_ROOT / "data" / "db" / "england.db"

# The four season articles that carry the six divisions, named as
# parse_wiki_results.DIVISION_SECTIONS keys them.
ARTICLES = ("National_League", "Isthmian_League", "Northern_Premier_League", "Southern_Football_League")
DIVISIONS = tuple(sorted(set(wiki.DIVISION_SECTIONS.values())))
RAW_URL = "https://en.wikipedia.org/w/index.php?title={title}&action=raw"
# Wikipedia refuses anonymous user agents; a descriptive one with a contact is its stated policy.
USER_AGENT = "english-ftbl26/1.0 (https://github.com/petedilworth/english-ftbl26; non-league results refresh)"
REDIRECT = re.compile(r"^\s*#REDIRECT\s*\[\[([^\]|#]+)", re.I)
MIN_CLUBS = 16

logger = logging.getLogger("refresh_nonleague")


def current_season_end_year(today: datetime.date | None = None) -> int:
    """The same rule as the Refresh workflow: a season ends the year after it starts in July."""
    today = today or datetime.date.today()
    return today.year + 1 if today.month >= 7 else today.year


def article_title(season_end_year: int, league: str) -> str:
    """'2026–27 National League', with the en dash Wikipedia uses."""
    return f"{season_end_year - 1}–{season_end_year % 100:02d} {league.replace('_', ' ')}"


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def fetch_wikitext(title: str, get=_http_get, hops: int = 3) -> str:
    """
    The article's wikitext. action=raw hands back a redirect page as the
    one line '#REDIRECT [[Target]]' rather than following it, so this does.
    """
    for _ in range(hops):
        text = get(RAW_URL.format(title=urllib.parse.quote(title)))
        m = REDIRECT.match(text)
        if not m:
            return text
        title = m.group(1).strip()
        logger.info("redirected to %s", title)
    raise RuntimeError(f"{title}: too many redirects")


def grids(season_end_year: int, texts: dict[str, str]) -> dict[str, dict]:
    """
    {division_id: grid} for the season, parsed by parse_wiki_results from
    the articles' wikitext. The parser reads the season and the league
    from the filename, so each text is written under the name it expects.
    """
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for league, text in texts.items():
            path = Path(tmp) / f"{season_end_year - 1}_{league}.wikitext"
            path.write_text(text, encoding="utf-8")
            for (season, division_id), g in wiki.parse_file(path).items():
                if season == season_end_year:
                    out[division_id] = g
    return out


def rows_for(division_id: str, g: dict) -> list[tuple]:
    """The CSV rows the parser writes, in its column order."""
    names = g["names"]
    return [(division_id, "", names.get(home, home), names.get(away, away), hg, ag,
             "H" if hg > ag else "A" if ag > hg else "D")
            for home, away, hg, ag in g["rows"]]


def committed(path: Path) -> dict | None:
    """What the committed file holds: its clubs and its fixtures with their scores."""
    if not path.exists():
        return None
    fixtures, clubs = {}, set()
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            fixtures[(r["HomeTeam"], r["AwayTeam"])] = (int(r["FTHG"]), int(r["FTAG"]))
            clubs.update((r["HomeTeam"], r["AwayTeam"]))
    return {"fixtures": fixtures, "clubs": clubs}


def problems(g: dict, old: dict | None, resolver: dict[str, str]) -> list[str]:
    """Why this grid must not replace the committed file; empty when it may."""
    out = []
    names, codes = g["names"], g["codes"]
    # A name the committed file already carries unresolved is tolerated - the
    # pipeline keeps such a club as a row with no page - so an old gap does not
    # freeze the division. A new one does, until club_master.csv knows it.
    known = old["clubs"] if old else set()
    unresolved = sorted({n for n in names.values()
                         if resolver.get(entities._normalize(n)) is None and n not in known})
    if unresolved:
        out.append("club name(s) this project cannot resolve: " + ", ".join(unresolved))
    clubs = {names.get(c, c) for c in codes}
    if len(codes) < MIN_CLUBS:
        out.append(f"only {len(codes)} clubs in the grid")
    rows = g["rows"]
    pairs = [(names.get(h, h), names.get(a, a)) for h, a, _, _ in rows]
    strangers = sorted({c for pair in pairs for c in pair if c not in clubs})
    if strangers:
        out.append("match(es) involving a club not in the grid: " + ", ".join(strangers))
    if len(set(pairs)) != len(pairs):
        out.append("a fixture is listed twice")
    if len(rows) > len(codes) * (len(codes) - 1):
        out.append(f"{len(rows)} matches is more than a round-robin of {len(codes)} holds")
    if old:
        if clubs != old["clubs"]:
            gone, new = sorted(old["clubs"] - clubs), sorted(clubs - old["clubs"])
            out.append("club list changed" + (f", gone: {', '.join(gone)}" if gone else "")
                       + (f", new: {', '.join(new)}" if new else ""))
        if len(rows) < len(old["fixtures"]):
            out.append(f"fewer matches than committed: {len(rows)} against {len(old['fixtures'])}")
        missing = sorted(set(old["fixtures"]) - set(pairs))
        if missing:
            out.append(f"{len(missing)} committed fixture(s) gone, first {missing[0][0]} v {missing[0][1]}")
    return out


def write(path: Path, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"])
        writer.writerows(rows)


def refresh(season_end_year: int, texts: dict[str, str], resolver: dict[str, str],
            out_dir: Path = OUT_DIR, dry_run: bool = False) -> dict[str, str]:
    """
    One line per division: "written", "unchanged", "no grid", or the
    reasons it was refused. Writes only the divisions that pass.
    """
    found = grids(season_end_year, texts)
    report = {}
    for division_id in DIVISIONS:
        g = found.get(division_id)
        if g is None:
            report[division_id] = "no grid in the article"
            continue
        path = out_dir / historical.nonleague_filename(season_end_year, division_id)
        old = committed(path)
        why = problems(g, old, resolver)
        if why:
            report[division_id] = "refused: " + "; ".join(why)
            continue
        rows = rows_for(division_id, g)
        new = {(r[2], r[3]): (r[4], r[5]) for r in rows}
        if old and new == old["fixtures"]:
            report[division_id] = f"unchanged, {len(rows)} matches"
            continue
        if not dry_run:
            write(path, rows)
        report[division_id] = (f"{'would write' if dry_run else 'written'}, {len(rows)} matches"
                               f" ({len(rows) - len(old['fixtures']) if old else len(rows):+d})")
    return report


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, default=current_season_end_year(),
                        help="season end year (default: the season in progress)")
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = parser.parse_args(argv)

    texts = {}
    for league in ARTICLES:
        title = article_title(args.season, league)
        try:
            texts[league] = fetch_wikitext(title)
            logger.info("fetched %s (%d characters)", title, len(texts[league]))
        except (urllib.error.URLError, RuntimeError, TimeoutError) as exc:
            logger.error("%s: %s", title, exc)
    if not texts:
        logger.error("nothing fetched; the committed files stand")
        return 2

    conn = sqlite3.connect(DB)
    resolver = entities.build_resolver(conn)
    conn.close()
    report = refresh(args.season, texts, resolver, Path(args.out), args.dry_run)
    refused = 0
    for division_id, line in sorted(report.items()):
        level = logging.ERROR if line.startswith(("refused", "no grid")) else logging.INFO
        refused += level == logging.ERROR
        logger.log(level, "%s: %s", division_id, line)
    if refused:
        logger.error("%d division(s) refused; their committed files stand", refused)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
