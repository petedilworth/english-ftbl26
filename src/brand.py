"""
The name on the door, in one place.

WHY THIS EXISTS. The site was called "English Football History" in three
templates and a licence file, and nowhere a link preview could read it:
no description, no image, no icon. A link sent to someone arrived as a
bare address. Renaming it meant deciding where a name lives, and the
answer is here - the templates, the preview cards and the tests all read
this module, so the next rename is one line.

THE NAME. "As it stands" is what the commentator says on the last day,
with the table changing under him: as it stands, they are going down.
It is the table, it is provisional, and it is the second half of every
sentence this site writes - a club's past, then where it stands.

THE COLOURS are a football pitch: mown green in two shades for the top of
every page, white for the lines and the words on it, and one yellow for
the word that matters. Below the pitch the page is light, because tables
and charts are read there and green is a poor thing to read numbers on.
They are here as well as in static/style.css because the preview cards
are drawn by Pillow, which cannot read a stylesheet. A test holds the two
together.
"""

from editions import config as _editions

NAME = "As It Stands"
# Credit lines written before the rename stay valid: NOTICE.md gives both.
FORMER_NAME = "English Football History"

TAGLINE = "English football since 1958, and where everyone has ended up."
STRAPLINE = "English football since 1958"   # the tagline's first half, where there is room for one
DESCRIPTION = (
    "Every club in the top seven tiers of English football and every season "
    "since 1958/59: the tables, the falls, the money, and where everyone "
    "stands now."
)

# One address for the whole project: the emails already needed an absolute
# one, so the site takes theirs rather than keeping a second copy.
SITE_URL = _editions.SITE_URL
REPO_URL = "https://github.com/petedilworth/english-ftbl26"

# The pitch. Two greens a shade apart are the mower's stripes; white text
# is 6.3:1 on the darker and 5.6:1 on the lighter, so it can be small.
PITCH = "#1b6b37"
PITCH_LIGHT = "#1f7740"
DEEP = "#0f4226"      # the logo's tile, and a button being pressed
CHALK = "#ffffff"     # the lines, and the words on the grass
FLAG = "#ffe169"      # corner-flag yellow: the present tense, on the pitch only.
                      # 4.3:1 on the lighter stripe, so it is for headlines, never small print.

# The page under the pitch. The tier palette stays in the stylesheet: it
# is data, not brand.
PAPER = "#f7f9f4"
CARD = "#ffffff"
INK = "#15181c"
MUTED = "#5a655d"
LINE = "#dfe5d9"
SPOT = PITCH          # the highlight on the light page is the pitch's own green
LINK = "#14633a"


def page_url(rel: str) -> str:
    """
    The public address of a built page, from its path under the site root.
    Directory form - /team/x/ not /team/x/index.html - because that is the
    address a person copies, and one page should have one address.
    """
    rel = rel.replace("\\", "/").lstrip("/")
    if rel == "index.html":
        rel = ""
    elif rel.endswith("/index.html"):
        rel = rel[: -len("index.html")]
    return f"{SITE_URL}/{rel}"


def context() -> dict:
    """What every template is handed, under the name `brand`."""
    return {
        "name": NAME, "tagline": TAGLINE, "description": DESCRIPTION,
        "site_url": SITE_URL, "repo_url": REPO_URL,
        # The colour a phone paints its own bars with: the pitch, so the
        # browser's top edge and the page's are one piece of grass.
        "theme": PITCH,
    }
