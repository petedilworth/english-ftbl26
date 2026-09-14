"""Paths, the site address, and the one hard limit."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "db" / "england.db"
ARCHIVE_ROOT = PROJECT_ROOT / "content" / "digests"
PREVIEW_ROOT = PROJECT_ROOT / "preview"
TEMPLATE_DIR = PROJECT_ROOT / "templates" / "email"
STRAIGHT_DATES = PROJECT_ROOT / "content" / "straight-dates.yml"

# Every page on the site links relatively, so the emails are the only
# place an absolute address is needed. Overridable for a fork or a
# custom domain.
SITE_URL = os.environ.get(
    "SITE_URL", "https://petedilworth.github.io/english-ftbl26"
).rstrip("/")

# Gmail clips a message at about 102 KB of HTML and hides the rest behind
# a link. The build fails above this so the clipping is never discovered
# in an inbox. Inline images are attachments and do not count.
SIZE_LIMIT = 90_000


def club_url(club_id: str) -> str:
    return f"{SITE_URL}/team/{club_id}/index.html"


def archive_url(edition: str, date_iso: str) -> str:
    return f"{SITE_URL}/digest/{edition}/{date_iso}/index.html"
