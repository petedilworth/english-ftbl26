"""What every edition produces, and the shape it is built from."""

import datetime
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EditionOutput:
    subject: str
    html: str
    text: str
    # (png_path, content_id) pairs referenced from the HTML as cid:content_id
    images: list[tuple[Path, str]] = field(default_factory=list)
    # The claims ledger: what this edition expected, with the table
    # snapshot the reviews need to say what happened. JSON-serializable.
    claims: list[dict] = field(default_factory=list)
    # The table as it stood when this edition was built, every club in
    # scope, so a later edition can say who moved. Written into
    # claims.json under "table".
    table: dict[str, dict] | None = None
    # Anything else the edition wants remembered in claims.json - the
    # reviews record which results they covered, so a late result is
    # caught up next week rather than lost.
    extra: dict = field(default_factory=dict)
    # Why the edition is short, when it is. Rendered as a plain line;
    # a thin week sends anyway and says so.
    thin: str | None = None


class Edition:
    """
    One kind of email. Subclasses set `name` and implement `build`.

    `build` is the facts layer: it decides what goes in and in what order,
    and hands structured data to a template. The words live in the
    template and in `phrasing.py`, nowhere else - see docs/voice.md.
    """

    name: str = ""

    def __init__(self, conn: sqlite3.Connection, date: datetime.date,
                 chart_dir: Path):
        self.conn = conn
        self.date = date
        self.chart_dir = chart_dir

    def build(self, **kwargs) -> EditionOutput:
        raise NotImplementedError
