"""
Download match-level CSVs from football-data.co.uk for seasons 1993/94 onward.
Files are cached in data/raw/ and never re-downloaded unless force=True.
"""

import datetime
import logging
import time
from pathlib import Path

import requests
import urllib3

# football-data.co.uk's certificate chain trips some Windows/Anaconda setups;
# verification is disabled for this one known host.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.football-data.co.uk/mmz4281"

# Tier 5 (EC = Conference/National League) data starts 2005/06 on the site
TIER5_FIRST_SEASON = 2006

TIER_TO_CODE = {1: "E0", 2: "E1", 3: "E2", 4: "E3", 5: "EC"}

# Inverse lookup, used to check a CSV really is the division we asked for.
CODE_TO_TIER = {code: tier for tier, code in TIER_TO_CODE.items()}


def current_season_end_year(today: datetime.date | None = None) -> int:
    """
    End year of the season currently in progress. A season starting in
    August of year N is the 'N+1' season, so July is treated as the rollover.
    """
    today = today or datetime.date.today()
    return today.year + 1 if today.month >= 7 else today.year


def division_code_in_csv(content: bytes) -> str | None:
    """
    Read the 'Div' value from a raw CSV body, or None if it has no Div column.

    football-data.co.uk stamps every row with its division code, which is the
    only trustworthy statement of what a file actually contains — the URL is
    not, since the site has served another division's file for a season that
    hasn't started yet.
    """
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        return None

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None

    header = [h.strip().strip('"') for h in lines[0].split(",")]
    if "Div" not in header:
        return None

    idx = header.index("Div")
    for line in lines[1:]:
        fields = line.split(",")
        if idx < len(fields):
            value = fields[idx].strip().strip('"')
            if value:
                return value
    return None


def season_to_str(season_end_year: int) -> str:
    """
    Convert a season end year to the two-pair string used in URLs.
    1994 → '9394', 2000 → '9900', 2001 → '0001', 2024 → '2324'
    """
    start = season_end_year - 1
    yy_start = start % 100
    yy_end = season_end_year % 100
    return f"{yy_start:02d}{yy_end:02d}"


def str_to_season(s: str) -> int:
    """
    Inverse of season_to_str.
    '9394' → 1994, '9900' → 2000, '0001' → 2001, '2324' → 2024
    """
    yy = int(s[2:4])
    return 2000 + yy if yy < 94 else 1900 + yy


def _season_published_yet(season_end_year: int, today: datetime.date | None = None) -> bool:
    """
    Whether football-data.co.uk should have files for this season yet.

    A season ending in year N starts the previous August. Before then its
    files simply don't exist, so a 404 is expected rather than a problem.
    """
    today = today or datetime.date.today()
    return today >= datetime.date(season_end_year - 1, 8, 1)


def build_url(season_end_year: int, tier: int) -> str:
    season_str = season_to_str(season_end_year)
    code = TIER_TO_CODE[tier]
    return f"{BASE_URL}/{season_str}/{code}.csv"


def download_csv(
    season_end_year: int,
    tier: int,
    raw_dir: Path,
    force: bool = False,
    session: requests.Session | None = None,
) -> Path | None:
    """
    Download one CSV. Returns the local Path on success, None on 404/skip.
    """
    season_str = season_to_str(season_end_year)
    tier_digit = tier - 1  # tier 1 → E0 digit
    filename = raw_dir / f"{season_str}_E{tier_digit}.csv"

    # The season in progress gains results every week, so a cached copy is
    # stale by definition — and a bad one would otherwise be reused forever.
    is_live_season = season_end_year >= current_season_end_year()

    if filename.exists() and not force and not is_live_season:
        logger.debug("Already cached: %s", filename.name)
        return filename

    url = build_url(season_end_year, tier)
    client = session or requests

    try:
        resp = client.get(url, timeout=30, verify=False)
    except requests.RequestException as exc:
        logger.error("Network error fetching %s: %s", url, exc)
        return None

    if resp.status_code == 404:
        if tier == 5 and season_end_year < TIER5_FIRST_SEASON:
            logger.debug("404 (expected - Tier 5 data starts later): %s", url)
        elif not _season_published_yet(season_end_year):
            # Pre-season: next season's files don't exist until around August.
            # Expected every run through the summer, so not worth a warning.
            logger.info("Not published yet: %s", url)
        else:
            logger.warning("404 unexpected for %s", url)
        return None

    if resp.status_code != 200:
        logger.error("HTTP %s for %s — skipping", resp.status_code, url)
        return None

    content = resp.content
    if len(content) < 10:
        logger.warning("Empty/tiny response for %s — skipping", url)
        return None

    if content.lstrip().startswith(b"<"):
        logger.warning("HTML error page returned for %s — skipping", url)
        return None

    # A 200 is not proof we got the division we asked for. When a season's
    # file doesn't exist yet the site has answered with another division's
    # data, which previously landed in the database under the wrong tier.
    expected_code = TIER_TO_CODE[tier]
    actual_code = division_code_in_csv(content)
    if actual_code is not None and actual_code != expected_code:
        logger.error(
            "%s returned %s data, not %s — refusing to save it as tier %d",
            url,
            actual_code,
            expected_code,
            tier,
        )
        return None

    raw_dir.mkdir(parents=True, exist_ok=True)
    filename.write_bytes(content)
    logger.info("Downloaded %s", filename.name)
    return filename


def download_all(
    raw_dir: Path,
    season_start: int = 1994,
    season_end: int | None = None,
    tiers: list[int] | None = None,
    force: bool = False,
) -> list[Path]:
    """
    Download all CSVs for every (season, tier) combination.
    Returns list of successfully downloaded or already-cached Paths.
    """
    if season_end is None:
        season_end = datetime.date.today().year
    if tiers is None:
        tiers = [1, 2, 3, 4, 5]

    downloaded: list[Path] = []
    session = requests.Session()
    session.verify = False
    session.headers.update({"User-Agent": "english-football-db/1.0"})

    total = sum(
        1
        for year in range(season_start, season_end + 1)
        for tier in tiers
        if not (tier == 5 and year < TIER5_FIRST_SEASON)
    )
    logger.info("Downloading up to %d files...", total)

    for year in range(season_start, season_end + 1):
        for tier in tiers:
            if tier == 5 and year < TIER5_FIRST_SEASON:
                continue

            path = download_csv(year, tier, raw_dir, force=force, session=session)
            if path is not None:
                downloaded.append(path)

            time.sleep(0.5)

    logger.info("Done. %d files available.", len(downloaded))
    return downloaded


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    project_root = Path(__file__).parent.parent
    raw_dir = project_root / "data" / "raw"
    download_all(raw_dir)
