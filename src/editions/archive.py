"""
Where an edition goes once built: the site archive, the dry-run preview
folder, and the marker that says it was sent.

Archive layout, one stream per edition type:

    content/digests/<edition>/<date>/index.html   browsable copy
    content/digests/<edition>/<date>/*.png        the charts
    content/digests/<edition>/<date>/claims.json  the claims ledger
    content/digests/<edition>/<date>/sent.json    written after a send
"""

import datetime
import json
import shutil
from pathlib import Path

from editions import config
from editions.base import EditionOutput


def _browsable(output: EditionOutput, image_prefix: str = "") -> str:
    """The HTML with cid: references swapped for file names."""
    html = output.html
    for path, cid in output.images:
        html = html.replace(f"cid:{cid}", f"{image_prefix}{path.name}")
    return html


def archive_dir(edition: str, date: datetime.date) -> Path:
    return config.ARCHIVE_ROOT / edition / date.isoformat()


def archive(output: EditionOutput, edition: str, date: datetime.date) -> Path:
    out = archive_dir(edition, date)
    out.mkdir(parents=True, exist_ok=True)
    for path, _ in output.images:
        shutil.copy(path, out / path.name)
    (out / "index.html").write_text(_browsable(output), encoding="utf-8")
    if output.claims or output.table:
        (out / "claims.json").write_text(
            json.dumps(claims_document(output, edition, date), indent=2),
            encoding="utf-8",
        )
    return out


def claims_document(output: EditionOutput, edition: str, date: datetime.date) -> dict:
    doc = {"edition": edition, "date": date.isoformat(),
           "subject": output.subject, "claims": output.claims}
    if output.table:
        doc["table"] = output.table
    return doc


def find_claims(edition: str, start: datetime.date, end: datetime.date) -> dict | None:
    """The latest claims.json for `edition` dated within [start, end], parsed."""
    stream = config.ARCHIVE_ROOT / edition
    if not stream.exists():
        return None
    for item in sorted(stream.iterdir(), reverse=True):
        try:
            when = datetime.date.fromisoformat(item.name)
        except ValueError:
            continue
        if start <= when <= end and (item / "claims.json").exists():
            try:
                return json.loads((item / "claims.json").read_text(encoding="utf-8"))
            except ValueError:
                return None
    return None


def write_preview(output: EditionOutput, edition: str) -> Path:
    """Dry run: a local copy under preview/<edition>/, charts alongside."""
    out = config.PREVIEW_ROOT / edition
    out.mkdir(parents=True, exist_ok=True)
    charts_dir = out / "charts"
    charts_dir.mkdir(exist_ok=True)
    for path, _ in output.images:
        if path.parent != charts_dir:
            shutil.copy(path, charts_dir / path.name)
    (out / "index.html").write_text(_browsable(output, "charts/"), encoding="utf-8")
    (out / "subject.txt").write_text(output.subject + "\n", encoding="utf-8")
    (out / "body.txt").write_text(output.text, encoding="utf-8")
    if output.claims or output.table:
        (out / "claims.json").write_text(
            json.dumps(claims_document(output, edition, datetime.date.today()), indent=2),
            encoding="utf-8")
    return out


def sent_marker(edition: str, date: datetime.date) -> Path:
    return archive_dir(edition, date) / "sent.json"


def mark_sent(edition: str, date: datetime.date, message_id: str, subject: str) -> None:
    marker = sent_marker(edition, date)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"message_id": message_id, "subject": subject,
                    "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                   indent=2),
        encoding="utf-8",
    )
