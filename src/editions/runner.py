"""
Build one edition and send it, or write it locally.

    python src/edition.py preview                 build and send
    python src/edition.py preview --dry-run       write preview/preview/, send nothing
    python src/edition.py auto                    whichever edition today is scheduled
    python src/edition.py preview --date 2026-09-04 --fixtures-file fixtures.csv

Every edition passes through the same gates: the size limit, the sent
marker (a re-run never sends twice unless --force), and the archive.
"""

import argparse
import datetime
import logging
import sqlite3
import sys
from pathlib import Path

from editions import archive, config
from editions.registry import EDITIONS, WEEKDAY_EDITIONS

logger = logging.getLogger(__name__)


def resolve_edition(name: str, date: datetime.date) -> str | None:
    if name != "auto":
        return name
    return WEEKDAY_EDITIONS.get(date.isoweekday())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and send one edition")
    parser.add_argument("edition", choices=sorted(EDITIONS) + ["auto"])
    parser.add_argument("--date", type=datetime.date.fromisoformat,
                        default=datetime.date.today(), help="the edition's date (ISO)")
    parser.add_argument("--dry-run", action="store_true",
                        help="write to preview/<edition>/ instead of sending")
    parser.add_argument("--force", action="store_true",
                        help="send even if this edition and date already has a sent marker")
    parser.add_argument("--db-path", type=Path, default=config.DB_PATH)
    parser.add_argument("--fixtures-file", type=Path,
                        help="preview only: read fixtures from this CSV instead of the network")
    parser.add_argument("--theme", help="catchment only: force a theme instead of the week's")
    parser.add_argument("--profile", help="catchment only: force the club profiled (club_id)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    name = resolve_edition(args.edition, args.date)
    if name is None:
        logger.info("No edition is scheduled for %s; nothing to do.", args.date.strftime("%A"))
        return 0
    if name not in EDITIONS:
        logger.error("Edition %r is scheduled but not built.", name)
        return 1

    if not args.db_path.exists():
        logger.error("Database not found at %s", args.db_path)
        return 1
    conn = sqlite3.connect(args.db_path)

    chart_dir = config.PREVIEW_ROOT / name / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    edition = EDITIONS[name](conn, args.date, chart_dir)
    kwargs = {}
    if args.fixtures_file:
        kwargs["fixtures_file"] = args.fixtures_file
    if args.theme:
        kwargs["theme"] = args.theme
    if args.profile:
        kwargs["profile_id"] = args.profile
    output = edition.build(**kwargs)

    size = len(output.html.encode("utf-8"))
    if size > config.SIZE_LIMIT:
        logger.error("%s is %d bytes of HTML; the limit is %d. Not sending.",
                     name, size, config.SIZE_LIMIT)
        return 1
    logger.info("%s built: %d bytes, %d images, %d claims%s", name, size,
                len(output.images), len(output.claims),
                " (thin week)" if output.thin else "")

    if args.dry_run:
        out = archive.write_preview(output, name)
        logger.info("Dry run: wrote %s", out / "index.html")
        return 0

    marker = archive.sent_marker(name, args.date)
    if marker.exists() and not args.force:
        logger.info("%s for %s was already sent (%s). Use --force to send again.",
                    name, args.date, marker)
        return 0

    import notify
    message_id = notify.send_email(output.subject, output.html, output.text, output.images)
    out = archive.archive(output, name, args.date)
    archive.mark_sent(name, args.date, message_id, output.subject)
    logger.info("Sent and archived to %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
