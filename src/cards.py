"""
The cards: what a link to this site looks like before anyone opens it.

A link sent in a message arrives as a picture, a title and a line of
text, fetched by the messaging app from the page's meta tags. Until now
this site had none, so its links arrived as bare addresses. The picture
is the first impression and often the only one, so it is drawn here, at
build time, one PNG per page that deserves its own:

    home                 this week's hero sentence, and where that club
                         sits among the ninety-two
    allocation           the offer: a date of birth in, a club out
    allocation/<club>    "Assigned: Walsall" - what a shared notice shows,
                         so the person receiving it sees the sender's club
                         before they open anything
    replay               the pyramid as it stands
    team/<club>          the club, where it stands, and its tiers since
                         the record began

WHY PILLOW AND NOT A BROWSER. A headless browser would draw these from the
real stylesheet, and would add a browser to every build. Pillow is already
here (matplotlib brings it), reads the site's own font file, and draws
five hundred cards in about the time the charts take. The cost is that
the layout is arithmetic rather than CSS, which is why it is kept simple:
a few sizes of one typeface, two colours of ink, and the clubs' own.

WHY THEY ARE PALETTE PNGs. Flat colour and text compress to a few
kilobytes once the image is reduced to a palette; as truecolour the set
weighed more than the rest of the site. Drawn at twice the size and
scaled down first, so the edges are smooth before the palette is chosen.

Nothing here is allowed to stop a build. available() says whether cards
can be drawn at all (the font has to load, with its weight axis); the
builder asks once and offers no card it has not drawn.
"""

import logging
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import brand

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = PROJECT_ROOT / "static" / "fonts" / "newsreader-display.woff2"

W, H = 1200, 630          # what every large link preview is cropped to
S = 2                     # drawn at twice the size, then scaled down
MARGIN = 64
NEUTRAL = "#b8bec6"       # a club with no colours on the register


def available() -> bool:
    """Whether this machine can draw the cards: the font, and its weight axis."""
    try:
        _font(40, 800)
        return True
    except Exception as exc:  # no FreeType, no WOFF2 support, no variations
        logger.warning("Link preview cards skipped: %s", exc)
        return False


@lru_cache(maxsize=None)
def _font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_PATH), size * S)
    font.set_variation_by_axes([weight])
    return font


def _hex(colour: str | None, fallback: str = NEUTRAL) -> str:
    c = (colour or "").strip()
    if len(c) in (4, 7) and c.startswith("#"):
        try:
            int(c[1:], 16)
            return c
        except ValueError:
            pass
    return fallback


class Card:
    """A sheet of paper at twice the size, with the few things these cards draw."""

    def __init__(self):
        self.img = Image.new("RGB", (W * S, H * S), brand.PAPER)
        self.draw = ImageDraw.Draw(self.img)

    # ── Text ──────────────────────────────────────────────────────────────

    def width(self, text: str, size: int, weight: int) -> float:
        return self.draw.textlength(text, font=_font(size, weight)) / S

    def text(self, x: float, y: float, text: str, size: int, weight: int = 400,
             fill: str = brand.INK, anchor: str = "ls") -> float:
        """Draw one run on a baseline; returns the x it ended at."""
        self.draw.text((x * S, y * S), text, font=_font(size, weight), fill=fill, anchor=anchor)
        return x + self.width(text, size, weight)

    def label(self, x: float, y: float, text: str, size: int = 22, fill: str = brand.MUTED,
              tracking: float = 0.14, weight: int = 650, right: bool = False) -> float:
        """Small capitals, letterspaced: the kicker above a headline. Pillow has no tracking, so it is done by hand."""
        text = text.upper()
        gap = size * tracking
        total = sum(self.width(ch, size, weight) for ch in text) + gap * (len(text) - 1)
        if right:
            x -= total
        for ch in text:
            self.text(x, y, ch, size, weight, fill)
            x += self.width(ch, size, weight) + gap
        return x

    def wrap(self, runs: list[tuple[str, int, str]], size: int, max_width: float) -> list[list[tuple[str, int, str]]]:
        """
        Break styled runs - (text, weight, colour) - into lines no wider
        than max_width, on spaces. A run is never split inside a word.
        """
        words = []
        for text, weight, colour in runs:
            for word in text.split():
                words.append((word, weight, colour))
        lines, line, used = [], [], 0.0
        for word, weight, colour in words:
            w = self.width(word, size, weight)
            space = self.width(" ", size, weight) if line else 0
            if line and used + space + w > max_width:
                lines.append(line)
                line, used, space = [], 0.0, 0
            line.append((word, weight, colour))
            used += space + w
        if line:
            lines.append(line)
        return lines

    def paragraph(self, x: float, y: float, runs, size: int, max_width: float, leading: float = 1.06) -> float:
        """Draw wrapped runs from a first baseline; returns the baseline after the last line."""
        for line in self.wrap(runs, size, max_width):
            cx = x
            for i, (word, weight, colour) in enumerate(line):
                if i:
                    cx += self.width(" ", size, weight)
                cx = self.text(cx, y, word, size, weight, colour)
            y += size * leading
        return y

    def fit(self, blocks: list[list[tuple[str, int, str]]], max_width: float, max_height: float,
            sizes=(104, 96, 88, 80, 72, 66, 60, 54, 48, 42), leading: float = 1.06) -> int:
        """The largest size at which every block, each starting a new line, fits the box."""
        for size in sizes:
            lines = sum(len(self.wrap(runs, size, max_width)) for runs in blocks)
            widest = max((self.width(word, size, weight) for runs in blocks
                          for text, weight, _ in runs for word in text.split()), default=0)
            if lines * size * leading <= max_height and widest <= max_width:
                return size
        return sizes[-1]

    # ── Marks ─────────────────────────────────────────────────────────────

    def rect(self, x, y, w, h, fill, radius: float = 0, outline=None, width: float = 0):
        self.draw.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], radius=radius * S, fill=fill,
                                    outline=outline, width=int(width * S))

    def bead(self, x: float, y: float, r: float, a: str | None, b: str | None, ring: str | None = None):
        """A club: a disc in its two kit colours, outlined so a white kit shows on paper."""
        a = _hex(a)
        box = [(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S]
        self.draw.ellipse(box, fill=a)
        if b and _hex(b, a) != a:
            self.draw.pieslice(box, -90, 90, fill=_hex(b, a))
        self.draw.ellipse(box, outline="#8f8a80", width=max(1, int(0.8 * S)))
        if ring:
            g = r + 5
            self.draw.ellipse([(x - g) * S, (y - g) * S, (x + g) * S, (y + g) * S], outline=ring, width=int(3 * S))

    def mark(self, x: float, y: float, size: float = 56):
        """The logo: four steps on a dark tile, the top one in the spot colour (static/favicon.svg)."""
        u = size / 32
        self.rect(x, y, size, size, brand.INK, radius=7 * u)
        for bx, by, bw, colour in ((12, 4.4, 8, brand.SPOT), (9, 10.8, 14, brand.PAPER),
                                   (6, 17.2, 20, brand.PAPER), (3, 23.6, 26, brand.PAPER)):
            self.rect(x + bx * u, y + by * u, bw * u, 4 * u, colour, radius=u)

    def masthead(self, y: float = MARGIN):
        """Top left: the mark and the name, as they are in the site's header."""
        self.mark(MARGIN, y, 52)
        end = self.text(MARGIN + 68, y + 39, brand.NAME, 40, 750)
        self.text(end, y + 39, ".", 40, 750, brand.SPOT)

    def footer(self, text: str = "English football since 1958"):
        self.rect(MARGIN, H - 84, W - 2 * MARGIN, 1.5, brand.LINE)
        self.label(MARGIN, H - 48, text, 20)

    def kit(self, a: str | None, b: str | None, height: float = 26):
        """A band across the top in the club's two colours, ruled off below for the white ones."""
        a = _hex(a)
        self.rect(0, 0, W / 2, height, a)
        self.rect(W / 2, 0, W / 2, height, _hex(b, a))
        self.rect(0, height, W, 2, brand.INK)

    def stamp(self, text: str, cx: float, cy: float, angle: float = 7, size: int = 30):
        """A rubber stamp: outlined, letterspaced, and not quite straight."""
        text = text.upper()
        gap = size * 0.14
        tw = sum(self.width(ch, size, 800) for ch in text) + gap * (len(text) - 1)
        pw, ph = int((tw + 44) * S), int((size + 30) * S)
        layer = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle([2 * S, 2 * S, pw - 2 * S, ph - 2 * S], radius=8 * S, outline=brand.SPOT, width=4 * S)
        x = 22 * S
        for ch in text:
            d.text((x, ph / 2), ch, font=_font(size, 800), fill=brand.SPOT, anchor="lm")
            x += (self.width(ch, size, 800) + gap) * S
        layer = layer.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        self.img.paste(layer, (int(cx * S - layer.width / 2), int(cy * S - layer.height / 2)), layer)

    # ── Out ───────────────────────────────────────────────────────────────

    def save(self, path: Path) -> None:
        """
        Halved, reduced to a palette, written. Each step is the cheap one
        on purpose: there are five hundred of these in a build. reduce() is
        an exact two-by-two average, which is all a halving needs; the
        octree palette is a fifth of the time of median cut and keeps the
        paper its colour, where max-coverage turned it white; and the
        optimiser bought six per cent for as long as the drawing took.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        small = self.img.reduce(S)
        small = small.quantize(colors=255, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        small.save(path)


# ── The cards ─────────────────────────────────────────────────────────────

def home_card(path: Path, hero: dict | None, league: list[tuple] | None = None) -> None:
    """
    This week's sentence, set as the page sets it, over the ninety-two
    in table order with the hero's club ringed where it stands. `league`
    is [(club_id, colour, colour2)] top to bottom; without a hero the
    card carries the site's own line.
    """
    c = Card()
    c.masthead()
    if hero:
        blocks = [[(f"{hero['name']}.", 800, brand.INK), (hero["past"], 400, brand.INK)],
                  [(hero["present"], 400, brand.SPOT)]]
    else:
        blocks = [[("English football since 1958,", 800, brand.INK)],
                  [("and where everyone has ended up.", 400, brand.SPOT)]]
    box_w, box_h = W - 2 * MARGIN, 300
    size = c.fit(blocks, box_w, box_h)
    y = 150 + size * 0.86
    for runs in blocks:
        y = c.paragraph(MARGIN, y, runs, size, box_w)

    if league:
        # One row, every club, in order: twelve pixels each is what fits.
        n = len(league)
        pitch = min(22.0, (W - 2 * MARGIN) / n)
        r = pitch * 0.4
        base = H - 128
        where = None
        for i, (club_id, a, b) in enumerate(league):
            x = MARGIN + pitch * (i + 0.5)
            if hero and club_id == hero["club_id"]:
                where = (i, x)
                continue
            c.bead(x, base, r, a, b)
        if where:
            i, x = where
            c.bead(x, base, r * 1.7, hero.get("colour"), hero.get("colour2"), ring=brand.INK)
            note = f"{_ordinal(i + 1)} of {n}"
            tw = sum(c.width(ch, 18, 650) for ch in note.upper()) + 18 * 0.14 * (len(note) - 1)
            c.label(min(max(MARGIN, x - tw / 2), W - MARGIN - tw), base - 26, note, 18, brand.INK)
    c.footer()
    c.label(W - MARGIN, H - 48, "As it stands", 20, brand.SPOT, right=True)
    c.save(path)


def allocation_card(path: Path) -> None:
    """The offer, with the form drawn on it: three boxes and a button are the whole instruction."""
    c = Card()
    c.masthead()
    blocks = [[("A club will be assigned.", 800, brand.INK)], [("There is no appeals process.", 400, brand.SPOT)]]
    size = c.fit(blocks, W - 2 * MARGIN, 190)
    y = 150 + size * 0.86
    for runs in blocks:
        y = c.paragraph(MARGIN, y, runs, size, W - 2 * MARGIN)
    top = 388
    c.label(MARGIN, top - 14, "Date of birth", 20)
    x = MARGIN
    for text, w in (("DD", 120), ("MM", 120), ("YYYY", 170)):
        c.rect(x, top, w, 84, brand.CARD, radius=12, outline=brand.INK, width=2.5)
        tw = c.width(text, 36, 500)
        c.text(x + (w - tw) / 2, top + 55, text, 36, 500, "#b9b4a8")
        x += w + 14
    c.rect(x + 8, top, 330, 84, brand.INK, radius=42)
    tw = c.width("Assign a club", 34, 650)
    c.text(x + 8 + (330 - tw) / 2, top + 53, "Assign a club", 34, 650, brand.PAPER)
    c.footer("One date of birth. One club. For life.")
    c.save(path)


def assigned_card(path: Path, name: str, a: str | None, b: str | None) -> None:
    """What a shared notice shows: the sender's club, stamped, and the rule."""
    c = Card()
    c.kit(a, b)
    c.masthead(MARGIN + 6)
    c.label(MARGIN, 196, "Notice of allocation", 22)
    c.text(MARGIN, 250, "Someone you know has been assigned", 38, 400, brand.MUTED)
    blocks = [[(f"{name}.", 800, brand.INK)]]
    size = c.fit(blocks, W - 2 * MARGIN, 150, sizes=(132, 120, 108, 96, 86, 76, 68, 60, 54))
    y = c.paragraph(MARGIN, 262 + size * 0.9, blocks[0], size, W - 2 * MARGIN, leading=1.0)
    c.paragraph(MARGIN, y + 8, [("There is no appeals process.", 400, brand.SPOT)], 52, W - 2 * MARGIN)
    c.stamp("Allocated", W - MARGIN - 130, 112)
    c.footer("Which club do you get?")
    c.save(path)


def replay_card(path: Path, rows: list[list[tuple]], seasons: int, clubs: int) -> None:
    """The pyramid as it stands: `rows` is one list of (colour, colour2) per row of beads, top first."""
    c = Card()
    c.masthead()
    y = 150 + 84 * 0.86
    y = c.paragraph(MARGIN, y, [("The Replay.", 800, brand.INK)], 84, 520)
    c.paragraph(MARGIN, y + 4, [(f"{seasons} seasons and {clubs} clubs, every one a dot in its own colours.", 400, brand.INK)],
                40, 470, leading=1.14)
    widest = max((len(r) for r in rows), default=1)
    pitch = min(24.0, 560 / widest, 420 / max(1, len(rows)))
    left = W - MARGIN - widest * pitch
    top = 70 + (430 - len(rows) * pitch) / 2
    for j, row in enumerate(rows):
        offset = (widest - len(row)) / 2
        for i, (a, b) in enumerate(row):
            c.bead(left + (offset + i + 0.5) * pitch, top + (j + 0.5) * pitch, pitch * 0.39, a, b)
    c.footer("Press play, or follow one club through all of it")
    c.save(path)


def club_card(path: Path, name: str, a: str | None, b: str | None, where: str,
              history: list[tuple[int, int]], first: int, last: int) -> None:
    """A club's own card: its name, where it stands, and its tier in every season on record."""
    c = Card()
    c.kit(a, b)
    c.masthead(MARGIN + 6)
    blocks = [[(f"{name}.", 800, brand.INK)]]
    size = c.fit(blocks, W - 2 * MARGIN, 130, sizes=(116, 104, 94, 84, 76, 68, 60, 54))
    y = c.paragraph(MARGIN, 150 + size * 0.9, blocks[0], size, W - 2 * MARGIN, leading=1.0)
    # paragraph() hands back the next baseline at the headline's own size;
    # the line under it is a third of that size and sits closer.
    y = c.paragraph(MARGIN, y - size + 66, [(where, 400, brand.SPOT)], 42, W - 2 * MARGIN, leading=1.1)

    # Tier by season: up is up, one step a division, gaps where the record has none.
    if history and last > first:
        top, bottom = max(y - 8, 330), H - 112
        deepest = max(3, max(t for _, t in history))
        left, right = MARGIN + 26, W - MARGIN
        step = (right - left) / (last - first + 1)

        def sx(season): return left + (season - first) * step
        def sy(tier): return top + (tier - 1) / (deepest - 1) * (bottom - top)

        for tier in range(1, deepest + 1):
            c.rect(left, sy(tier), right - left, 1, brand.LINE)
            c.text(MARGIN, sy(tier) + 6, str(tier), 18, 500, brand.MUTED)
        prev = None
        for season, tier in history:
            x0, x1, yy = sx(season), sx(season) + step, sy(tier)
            if prev and prev[0] == season - 1 and prev[1] != tier:
                c.draw.line([x0 * S, sy(prev[1]) * S, x0 * S, yy * S], fill=brand.INK, width=int(3.5 * S))
            c.draw.line([x0 * S, yy * S, x1 * S, yy * S], fill=brand.INK, width=int(3.5 * S))
            prev = (season, tier)
        if prev:
            x, yy = sx(prev[0]) + step, sy(prev[1])
            c.draw.ellipse([(x - 8) * S, (yy - 8) * S, (x + 8) * S, (yy + 8) * S], fill=brand.SPOT)
    c.footer(f"{first - 1}/{first % 100:02d} to {last - 1}/{last % 100:02d}")
    c.label(W - MARGIN, H - 48, "As it stands", 20, brand.SPOT, right=True)
    c.save(path)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


# ── Icons ─────────────────────────────────────────────────────────────────

def write_icons(out_dir: Path) -> None:
    """
    The mark as PNGs, for the places an SVG is not accepted: the home
    screen of a phone, and the manifest that names the site when it is
    put there. Full-bleed, because iOS rounds the corners itself.
    """
    for name, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)):
        big = Image.new("RGB", (size * 4, size * 4), brand.INK)
        d = ImageDraw.Draw(big)
        u = size * 4 / 32
        inset = 3.2   # the steps drawn a little smaller than on the tile, clear of the rounded mask
        k = (32 - 2 * inset) / 32
        for bx, by, bw, colour in ((12, 4.4, 8, brand.SPOT), (9, 10.8, 14, brand.PAPER),
                                   (6, 17.2, 20, brand.PAPER), (3, 23.6, 26, brand.PAPER)):
            x0, y0 = (inset + bx * k) * u, (inset + by * k) * u
            d.rounded_rectangle([x0, y0, x0 + bw * k * u, y0 + 4 * k * u], radius=k * u, fill=colour)
        big.resize((size, size), Image.Resampling.LANCZOS).save(out_dir / name, optimize=True)
