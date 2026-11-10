"""The name, the address and the colours: one place, and everything else agreeing with it."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import brand  # noqa: E402

ROOT = Path(__file__).parent.parent
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def _token(name):
    return re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", CSS).group(1).lower()


def test_the_stylesheet_and_the_cards_use_the_same_colours():
    # The cards are drawn by Pillow, which cannot read a stylesheet, so the
    # values exist twice. This is what stops them drifting.
    assert _token("pitch") == brand.PITCH
    assert _token("pitch-light") == brand.PITCH_LIGHT
    assert _token("pitch-deep") == brand.DEEP
    assert _token("flag") == brand.FLAG
    assert _token("bg") == brand.PAPER
    assert _token("ink") == brand.INK
    assert _token("muted") == brand.MUTED
    assert _token("line") == brand.LINE
    assert _token("spot") == brand.SPOT
    assert _token("accent") == brand.LINK
    mark = (ROOT / "static" / "favicon.svg").read_text()
    assert brand.DEEP in mark and brand.FLAG in mark and brand.CHALK in mark
    assert (ROOT / "templates" / "_mark.svg").read_text().count("<rect") == mark.count("<rect")
    assert brand.DEEP in (ROOT / "templates" / "_mark.svg").read_text()


def _contrast(a, b):
    def lum(h):
        parts = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, bl = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in parts)
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_palette_can_be_read():
    """
    A green theme is only worth having if the words on it can be read.
    4.5:1 is the mark for ordinary text and 3:1 for headlines; the yellow
    is held to the headline mark because that is the only size it is used
    at, and the test says so in case someone uses it smaller.
    """
    for stripe in (brand.PITCH, brand.PITCH_LIGHT):
        assert _contrast(brand.CHALK, stripe) >= 4.5, "white words on the grass"
        assert _contrast(brand.FLAG, stripe) >= 3.0, "the yellow headline on the grass"
    assert _contrast(brand.FLAG, brand.PITCH_LIGHT) < 4.5, "if this ever passes, the yellow may be used small"
    for paper in (brand.PAPER, brand.CARD):
        assert _contrast(brand.INK, paper) >= 7
        assert _contrast(brand.MUTED, paper) >= 4.5
        assert _contrast(brand.LINK, paper) >= 4.5
        assert _contrast(brand.SPOT, paper) >= 4.5
    assert _contrast(brand.CHALK, brand.DEEP) >= 7


def test_a_page_has_one_address_and_it_is_the_one_a_person_would_copy():
    assert brand.page_url("index.html") == brand.SITE_URL + "/"
    assert brand.page_url("team/luton-town-fc/index.html") == brand.SITE_URL + "/team/luton-town-fc/"
    assert brand.page_url("404.html") == brand.SITE_URL + "/404.html"
    assert not brand.SITE_URL.endswith("/")


def test_the_name_is_written_in_one_place():
    # A template or script that spells the name out will be missed by the next rename.
    offenders = []
    for path in list((ROOT / "templates").glob("*.html")) + list((ROOT / "static").glob("*.js")):
        text = path.read_text(encoding="utf-8")
        if brand.NAME in text or brand.FORMER_NAME in text:
            offenders.append(path.name)
    assert not offenders, f"use {{{{ brand.name }}}} instead: {offenders}"
    assert brand.context()["name"] == brand.NAME and brand.NAME != brand.FORMER_NAME


def test_the_font_is_here_with_its_licence():
    fonts = ROOT / "static" / "fonts"
    assert (fonts / "newsreader-display.woff2").stat().st_size < 60_000, "the headline face is meant to be small"
    assert "SIL Open Font License" in (fonts / "OFL.txt").read_text(encoding="utf-8")
    assert 'url("fonts/newsreader-display.woff2")' in CSS and "font-display: swap" in CSS
