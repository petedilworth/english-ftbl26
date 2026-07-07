"""
Download match-level CSVs from football-data.co.uk for seasons 1993/94 onward.
Files are cached in data/raw/ and never re-downloaded unless force=True.
"""

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

    if filename.exists() and not force:
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
        if tier == 5:
            logger.debug("404 (expected for early Tier 5): %s", url)
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
    import datetime

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
