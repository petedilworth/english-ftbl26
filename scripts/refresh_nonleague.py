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
import collections
import csv
import datetime
import logging
import os
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


def annotate(level: str, message: str) -> None:
    """
    Say it where it can be read. The run's log lives on a host this
    sandbox cannot reach, but its annotations come back through the API,
    so every refusal and every "no grid" is also an annotation.
    """
    logger.log(logging.ERROR if level == "error" else logging.INFO, "%s", message)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level}::{message[:2000]}", flush=True)


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


HEADINGS = {division_id: (league, heading) for (league, heading), division_id in wiki.DIVISION_SECTIONS.items()}
# A results subsection that holds no grid of its own but one template call
# has the grid on that template's page: {{2026–27 National League North results}}.
TRANSCLUSION = re.compile(r"\{\{\s*(:?)([^{}|#]+?)\s*(?:\||\}\})")
NOT_A_GRID = ("sports results", "fb ", "efn", "cite", "main", "updated", "legend", "see also", "refn")


def _section(text: str, league: str, division_id: str) -> str | None:
    """The level-2 section of the article that is this division, if it has one."""
    parts = wiki.SECTION_2.split(text)
    for i in range(1, len(parts), 2):
        if wiki.DIVISION_SECTIONS.get((league, parts[i])) == division_id:
            return parts[i + 1]
    return None


def _parse(season_end_year: int, league: str, text: str, tmp: Path) -> dict[str, dict]:
    path = tmp / f"{season_end_year - 1}_{league}.wikitext"
    path.write_text(text, encoding="utf-8")
    return {division_id: g for (season, division_id), g in wiki.parse_file(path).items()
            if season == season_end_year}


def _schema(text: str) -> dict[str, int]:
    """The parameter names a template page uses, by prefix: what kind of table it is."""
    counts = collections.Counter(m.lower() for m in re.findall(r"\|\s*([A-Za-z]+)[_\d]", text))
    return dict(counts.most_common(12))


def _snippet(text: str, n: int = 700) -> str:
    i = text.find("match_")
    start = max(0, i - 120) if i >= 0 else 0
    return text[start:start + n]


def _transcluded(body: str, season_end_year: int) -> list[str]:
    """
    Page titles the results subsection pulls its grid from, in order. Only
    pages named for the season: a table template transcludes {{nowrap}}
    and {{1}} and the like too, and those lead nowhere.
    """
    labels = (f"{season_end_year - 1}\u2013{season_end_year % 100:02d}", f"{season_end_year - 1}-{season_end_year % 100:02d}")
    titles = []
    for colon, name in TRANSCLUSION.findall(body):
        name = name.strip()
        if name.lower().startswith(NOT_A_GRID) or not any(label in name for label in labels):
            continue
        titles.append(name if colon else f"Template:{name}")
    return list(dict.fromkeys(titles))


def grids(season_end_year: int, texts: dict[str, str], get=None) -> dict[str, dict]:
    """
    {division_id: grid} for the season, parsed by parse_wiki_results from
    the articles' wikitext. The parser reads the season and the league
    from the filename, so each text is written under the name it expects.

    A division whose results subsection holds no grid, only a template
    call, has its grid on that template's page; with a fetcher, that page
    is fetched and parsed in the subsection's place. Whatever is found or
    not is said as an annotation, because the log cannot be read from here.
    """
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for league, text in texts.items():
            found = _parse(season_end_year, league, text, Path(tmp))
            for division_id, (lg, heading) in HEADINGS.items():
                if lg != league:
                    continue
                notes = []
                section = _section(text, league, division_id)
                if section is None:
                    notes.append(f"no '{heading}' section; level-2 headings: "
                                 f"{[h.strip() for h in wiki.SECTION_2.findall(text)][:12]!r}")
                    annotate("warning", f"{division_id}: " + " | ".join(notes))
                    continue
                body = wiki._results_body(section)
                g = found.get(division_id)
                if body is not None and g and g["codes"] and g["rows"]:
                    out[division_id] = g
                    continue
                if body is None:
                    # No results subsection: a table subsection with show_matches carries the grid
                    # inline, so the whole section is read as one; failing that, the season's
                    # templates the section transcludes.
                    # Its own level-3 headings go, or the stand-in's Results body ends at the first of them.
                    flat = wiki.SECTION_3.sub("", section)
                    stand_in = f"== {heading} ==\n=== Results ===\n{flat}\n"
                    g = _parse(season_end_year, league, stand_in, Path(tmp)).get(division_id)
                    if g and g["codes"] and g["rows"]:
                        annotate("notice", f"{division_id}: grid read from the '{heading}' section itself: "
                                           f"{len(g['codes'])} clubs, {len(g['rows'])} matches")
                        out[division_id] = g
                        continue
                    titles = _transcluded(section, season_end_year)
                    every = [n.strip() for _, n in TRANSCLUSION.findall(section)][:8]
                    notes.append(f"no results subsection; level-3 headings "
                                 f"{[h.strip() for h in wiki.SECTION_3.findall(section)]!r}; transclusions {every!r}; "
                                 f"trying {titles!r}; parameters {_schema(section)}; near its first match_: "
                                 f"{_snippet(section, 300)!r}")
                else:
                    titles = _transcluded(body, season_end_year)
                    notes.append(f"results subsection holds no grid, starts {body.strip()[:160]!r}; trying {titles!r}")
                g = _follow(season_end_year, league, heading, division_id, titles, get, Path(tmp), notes)
                if g:
                    out[division_id] = g
                else:
                    annotate("warning", f"{division_id}: " + " | ".join(notes))
    return out


def _follow(season_end_year, league, heading, division_id, titles, get, tmp, notes, depth: int = 2) -> dict | None:
    """
    Fetch each transcluded page and parse it as the grid; a page with no
    grid of its own may transclude another, so follow those too, two deep.
    Every page that is not the grid adds what it holds to the notes.
    """
    if not get:
        return None
    queue, seen = [(t, 0) for t in titles], set()
    while queue:
        title, level = queue.pop(0)
        if title in seen or level > depth:
            continue
        seen.add(title)
        try:
            text = fetch_wikitext(title, get=get)
        except Exception as exc:        # a template page that is not there is just not the grid
            notes.append(f"{title}: {exc}")
            continue
        stand_in = f"== {heading} ==\n=== Results ===\n{text}\n"
        g = _parse(season_end_year, league, stand_in, tmp).get(division_id)
        if g and g["codes"] and g["rows"]:
            annotate("notice", f"{division_id}: grid read from {title}: {len(g['codes'])} clubs, "
                               f"{len(g['rows'])} matches")
            return g
        inner = [t for t in _transcluded(text, season_end_year) if t not in seen]
        notes.append(f"{title} holds no grid; parameters {_schema(text)}; transclusions {inner[:4]!r}; "
                     f"near its first match_: {_snippet(text, 400)!r}")
        queue.extend((t, level + 1) for t in inner)
    return None


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
        # A club may appear - it had no result when the file was committed - but
        # a club in the committed file cannot vanish.
        gone = sorted(old["clubs"] - clubs)
        if gone:
            out.append(f"club(s) gone from the grid: {', '.join(gone)}")
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
            out_dir: Path = OUT_DIR, dry_run: bool = False, get=None) -> dict[str, str]:
    """
    One line per division: "written", "unchanged", "no grid", or the
    reasons it was refused. Writes only the divisions that pass.
    """
    found = grids(season_end_year, texts, get=get)
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
            annotate("error", f"{title}: {exc}")
    if not texts:
        logger.error("nothing fetched; the committed files stand")
        return 2

    conn = sqlite3.connect(DB)
    resolver = entities.build_resolver(conn)
    conn.close()
    report = refresh(args.season, texts, resolver, Path(args.out), args.dry_run, get=_http_get)
    refused = 0
    for division_id, line in sorted(report.items()):
        bad = line.startswith(("refused", "no grid"))
        refused += bad
        annotate("error" if bad else "notice", f"{division_id}: {line}")
    if refused:
        annotate("error", f"{refused} division(s) refused; their committed files stand")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
