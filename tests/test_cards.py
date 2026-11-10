"""The link preview cards: the right size, small, on the pitch, and never a reason to fail a build."""

import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import brand  # noqa: E402
import cards  # noqa: E402

pytestmark = pytest.mark.skipif(not cards.available(), reason="this Pillow cannot read the font")

HERO = {"club_id": "giant-fc", "name": "Giant FC", "past": "Champions of England, 2015/16.",
        "present": "Tenth in League One.", "colour": "#003090", "colour2": "#FDBE11"}
LEAGUE = [("top-fc", "#EF0107", "#FFFFFF")] * 53 + [("giant-fc", "#003090", "#FDBE11")] + [("low-fc", None, None)] * 38


def _rgb(hex_colour):
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


def _near(a, b, by=4):
    return all(abs(p - q) <= by for p, q in zip(a, b))


def _check(path):
    img = Image.open(path)
    assert img.size == (cards.W, cards.H) == (1200, 630)
    assert img.mode == "P", "cards are palette PNGs: as truecolour they outweigh the site"
    assert path.stat().st_size < 120_000
    # The card is the pitch: the bottom corners are grass, one stripe each,
    # and still the right greens after the palette was chosen.
    rgb = img.convert("RGB")
    assert _near(rgb.getpixel((6, cards.H - 6)), _rgb(brand.PITCH)), rgb.getpixel((6, cards.H - 6))
    assert _near(rgb.getpixel((cards.STRIPE + 6, cards.H - 6)), _rgb(brand.PITCH_LIGHT))
    return rgb


def test_every_kind_of_card_draws(tmp_path):
    cards.home_card(tmp_path / "home.png", HERO, LEAGUE)
    cards.home_card(tmp_path / "plain.png", None, None)            # a database with no hero still gets a card
    cards.replay_card(tmp_path / "replay.png", [[("#EF0107", "#FFFFFF")] * 20, [(None, None)] * 24], 69, 359)
    cards.club_card(tmp_path / "club.png", "Luton Town", "#F78F1E", "#002D62", "As it stands: fourth in League One.",
                    [(1959, 1), (1960, 1), (1961, 2), (1963, 3), (2027, 3)], 1959, 2027)
    for name in ("home", "plain", "replay", "club"):
        _check(tmp_path / f"{name}.png")
    assert not hasattr(cards, "allocation_card") and not hasattr(cards, "assigned_card")


def test_the_words_on_a_card_are_white_and_the_one_that_matters_is_yellow(tmp_path):
    cards.home_card(tmp_path / "home.png", HERO, LEAGUE)
    colours = {c for _n, c in Image.open(tmp_path / "home.png").convert("RGB").getcolors(maxcolors=1200 * 630)}
    assert any(_near(c, _rgb(brand.CHALK), 2) for c in colours), "the headline is white"
    assert any(_near(c, _rgb(brand.FLAG), 6) for c in colours), "the present tense is yellow"


def test_the_longest_names_are_shrunk_to_fit_rather_than_cut_off(tmp_path):
    # Anything white in the margin on the right would mean a name ran off the card.
    for i, name in enumerate(("Brighton & Hove Albion", "Hampton & Richmond Borough", "Wolverhampton Wanderers",
                              "Northern Premier League Premier Division Athletic")):
        cards.club_card(tmp_path / f"c{i}.png", name, "#0057B8", None, "Not in the record this season.", [], 1959, 2027)
        img = _check(tmp_path / f"c{i}.png")
        edge = img.crop((cards.W - 24, 140, cards.W, 500))
        colours = [c for _n, c in edge.getcolors(maxcolors=edge.width * edge.height)]
        assert all(min(c) < 150 for c in colours), name      # grass and markings only: nothing near white


def test_a_club_with_no_colours_or_bad_ones_still_gets_a_card(tmp_path):
    cards.club_card(tmp_path / "none.png", "Nameless Town", None, None, "Not in the record this season.", [], 1959, 2027)
    cards.club_card(tmp_path / "bad.png", "Odd FC", "not-a-colour", "#12", "Last seen twenty-fourth in League Two, 1961/62.",
                    [(1962, 4)], 1959, 2027)
    _check(tmp_path / "none.png")
    _check(tmp_path / "bad.png")
    assert cards._hex("#FFF") == "#FFF" and cards._hex("red") == cards.NEUTRAL and cards._hex(None, "#000000") == "#000000"


def test_the_hero_is_ringed_where_it_stands_among_the_ninety_two(tmp_path):
    cards.home_card(tmp_path / "with.png", HERO, LEAGUE)
    cards.home_card(tmp_path / "without.png", dict(HERO, club_id="someone-else"), LEAGUE)
    assert (tmp_path / "with.png").read_bytes() != (tmp_path / "without.png").read_bytes()
    assert cards._ordinal(54) == "54th" and cards._ordinal(1) == "1st" and cards._ordinal(12) == "12th" \
        and cards._ordinal(22) == "22nd" and cards._ordinal(93) == "93rd"


def test_the_icons_are_the_sizes_a_phone_asks_for(tmp_path):
    cards.write_icons(tmp_path)
    for name, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)):
        img = Image.open(tmp_path / name).convert("RGB")
        assert img.size == (size, size)
        assert img.getpixel((2, 2)) == _rgb(brand.DEEP)            # full bleed: the phone rounds the corners
