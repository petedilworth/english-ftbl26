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
    assert _token("bg") == brand.PAPER
    assert _token("ink") == brand.INK
    assert _token("muted") == brand.MUTED
    assert _token("line") == brand.LINE
    assert _token("spot") == brand.SPOT
    assert _token("accent") == brand.LINK
    mark = (ROOT / "static" / "favicon.svg").read_text()
    assert brand.INK in mark and brand.SPOT in mark and brand.PAPER in mark
    assert (ROOT / "templates" / "_mark.svg").read_text().count("<rect") == mark.count("<rect")


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
