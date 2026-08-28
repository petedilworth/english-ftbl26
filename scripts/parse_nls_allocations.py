#!/usr/bin/env python3
"""
Extract the FA's National League System club allocations from their PDF.

WHY BY HAND. thefa.com is refused at this environment's network proxy, so
the document arrives as a file rather than a fetch, and there is no PDF
tooling installed - no pdftotext, no pypdf, no poppler. None is needed.
The pages are Flate-compressed content streams of ordinary text operators,
which zlib and re can read, and doing it this way keeps the dependency
list where it is.

WHAT THE DOCUMENT IS. Four steps of the pyramid, one column per division,
each club on a numbered row. Steps 1 and 2 are tiers 5 and 6 on this
site's numbering; step 3 is tier 7. It is the governing body's own list
and it settles in one place both halves of what the roster needs: which
clubs exist below the fifth tier, and which division each is in.

WHY THE RANK NUMBER MATTERS. A column also contains its heading, the page
footer and a legend, all at the same x. Rather than blacklist those, a row
counts only if it carries its rank number in the number column beside it -
headings and legends have none. The count assertion at the end is the
real quality control: every division in this document has a known size,
so a parse that loses a row or invents one fails rather than shipping.

    python3 scripts/parse_nls_allocations.py ALLOCATIONS.pdf
"""

import argparse
import re
import sys
import zlib
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# NOT data/raw/, which is gitignored: that directory is for files the
# pipeline can fetch again, and this one is extracted from a PDF on a
# host the proxy refuses. Losing it would mean losing the only record
# of who plays where now.
OUT = PROJECT_ROOT / "data" / "nls-allocations-2026-27.tsv"

SOURCE_URL = ("https://www.thefa.com/-/media/thefacom-new/files/competitions/"
              "2026-27/nls/nls-1-to-4-club-allocations-2026-27---v1-140526.ashx")

# Column geometry, in PDF user units. The rank sits in a narrow column of
# its own; the name starts about 24 units to its right and may run on in
# several fragments, which is how "Spaldin|g Un|ited" is printed.
COLUMNS = [
    # rank_x, name_from, name_to, column letter
    (150.6, 172.0, 383.0, "A"),
    (383.9, 405.0, 617.0, "B"),
    (617.3, 638.0, 850.0, "C"),
    (850.7, 872.0, 1100.0, "D"),
]
RANK_TOLERANCE = 6.0

# Which section a content stream belongs to. Streams 1-3 carry steps 1 and
# 2; stream 4 carries the tail of those columns above the step 3 headings
# at y=400, and step 3 below them; streams 5-8 are step 3; stream 9 is
# step 4, which this site does not model.
def _section(stream: int, y: float) -> str:
    if stream < 4 or (stream == 4 and y > 400):
        return "s12"
    return "s3" if stream < 9 else "s4"


DIVISIONS = {
    ("s12", "A"): ("National League", 5),
    ("s12", "C"): ("National League North", 6),
    ("s12", "D"): ("National League South", 6),
    ("s3", "A"): ("Isthmian League Premier", 7),
    ("s3", "B"): ("Northern Premier League Premier", 7),
    ("s3", "C"): ("Southern League Premier Central", 7),
    ("s3", "D"): ("Southern League Premier South", 7),
}

EXPECTED = {
    "National League": 24,
    "National League North": 24,
    "National League South": 24,
    "Isthmian League Premier": 22,
    "Northern Premier League Premier": 22,
    "Southern League Premier Central": 22,
    "Southern League Premier South": 22,
}

TM = re.compile(rb"([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+Tm")
TD = re.compile(rb"([-\d.]+)\s+([-\d.]+)\s+T[dD]")
PDF_STRING = re.compile(rb"\((?:\\.|[^\\()])*\)", re.S)
ESCAPES = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12,
           0x28: 40, 0x29: 41, 0x5C: 92}


def _unescape(raw: bytes) -> str:
    """PDF literal string to text. Backslash escapes and octal codes."""
    out, i = bytearray(), 0
    while i < len(raw):
        c = raw[i]
        if c == 0x5C and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt in ESCAPES:
                out.append(ESCAPES[nxt])
                i += 2
                continue
            if 0x30 <= nxt <= 0x37:
                j, digits = i + 1, b""
                while j < len(raw) and 0x30 <= raw[j] <= 0x37 and len(digits) < 3:
                    digits += bytes([raw[j]])
                    j += 1
                out.append(int(digits, 8) & 0xFF)
                i = j
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    return bytes(out).decode("cp1252", "replace")


def text_items(pdf: Path):
    """Every drawn string in the document, with the position it was drawn at."""
    data = pdf.read_bytes()
    streams = re.findall(rb"stream\r?\n(.*?)endstream", data, re.S)

    index = 0
    for blob in streams:
        try:
            content = zlib.decompress(blob)
        except zlib.error:
            continue                       # an image or a font, not a page
        if b"Tj" not in content and b"TJ" not in content:
            continue
        index += 1

        x = y = 0.0
        for line in content.split(b"\n"):
            m = TM.search(line)
            if m:
                x, y = float(m.group(5)), float(m.group(6))
            m = TD.search(line)
            if m:
                x += float(m.group(1))
                y += float(m.group(2))
            if b"Tj" in line or b"TJ" in line:
                text = "".join(_unescape(s[1:-1])
                               for s in PDF_STRING.findall(line)).strip()
                if text:
                    yield index, x, y, text


def parse(pdf: Path) -> list[tuple[str, int, int, str]]:
    ranks: dict = defaultdict(dict)
    fragments: dict = defaultdict(list)

    for stream, x, y, text in text_items(pdf):
        # A row is keyed by its section and its height on the page, NOT by
        # which content stream drew it. The table runs continuously down
        # the page while the streams break wherever they like, so a row's
        # rank number and its name are repeatedly drawn in different
        # streams - Carlisle United and its 7 are one such pair. Within a
        # section y decreases monotonically, so it identifies the row.
        row = (_section(stream, y), round(y, 1))
        for rank_x, name_from, name_to, column in COLUMNS:
            if abs(x - rank_x) < RANK_TOLERANCE and text.isdigit():
                ranks[row][column] = int(text)
                break
            if name_from <= x < name_to:
                fragments[(row, column)].append((x, text))
                break

    out = []
    for (row, column), items in fragments.items():
        division = DIVISIONS.get((row[0], column))
        if division is None:
            continue                       # step 1's number column, or step 4
        rank = ranks.get(row, {}).get(column)
        if rank is None:
            continue                       # a heading, a footer, or the legend
        name = "".join(t for _, t in sorted(items)).strip()
        if name:
            out.append((division[0], division[1], rank, name))

    return sorted(out, key=lambda r: (r[1], r[0], r[2]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="the FA club allocations PDF")
    parser.add_argument("-o", "--out", default=str(OUT))
    parser.add_argument("--retrieved", default="2026-08-28",
                        help="date the document was obtained")
    args = parser.parse_args()

    rows = parse(Path(args.pdf))

    counts = defaultdict(int)
    for division, _, _, _ in rows:
        counts[division] += 1

    problems = []
    for division, expected in EXPECTED.items():
        got = counts.get(division, 0)
        if got != expected:
            problems.append(f"{division}: parsed {got}, expected {expected}")
    for division, rank_rows in [(d, [r for r in rows if r[0] == d]) for d in counts]:
        seen = sorted(r[2] for r in rank_rows)
        if seen != list(range(1, len(seen) + 1)):
            problems.append(f"{division}: ranks are not 1..n - {seen}")

    for division in sorted(counts):
        print(f"  {division:34} {counts[division]:3}", file=sys.stderr)

    if problems:
        # The document's divisions have known sizes. A parse that loses a
        # row would put a town's population in nobody's hands, silently,
        # so it fails here instead.
        for p in problems:
            print(f"FAIL {p}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"# FA National League System club allocations, 2026/27\n")
        fh.write(f"# source: {SOURCE_URL}\n")
        fh.write(f"# retrieved: {args.retrieved}\n")
        fh.write("division\ttier\trank\tclub_name\n")
        for division, tier, rank, name in rows:
            fh.write(f"{division}\t{tier}\t{rank}\t{name}\n")
    print(f"wrote {len(rows)} rows to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
