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

THE COLOURS are here as well as in static/style.css because the preview
cards are drawn by Pillow, which cannot read a stylesheet. A test holds
the two together.
"""

from editions import config as _editions

NAME = "As It Stands"
# Credit lines written before the rename stay valid: NOTICE.md gives both.
FORMER_NAME = "English Football History"

TAGLINE = "English football since 1958, and where everyone has ended up."
STRAPLINE = "English football since 1958"   # the tagline's first half, where there is room for one
DESCRIPTION = (
    "Every club in the top seven tiers of English football and every season "
    "since 1958/59: the tables, the falls, the money, and a club assigned to "
    "you by date of birth. There is no appeals process."
)

# One address for the whole project: the emails already needed an absolute
# one, so the site takes theirs rather than keeping a second copy.
SITE_URL = _editions.SITE_URL
REPO_URL = "https://github.com/petedilworth/english-ftbl26"

# Paper, ink and one spot colour. The tier palette stays in the stylesheet:
# it is data, not brand.
PAPER = "#fbf9f4"
CARD = "#ffffff"
INK = "#15181c"
MUTED = "#5d6672"
LINE = "#e6e1d6"
SPOT = "#d4401f"      # vermillion: the present tense, wherever it appears
LINK = "#1d4f91"


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
        "site_url": SITE_URL, "repo_url": REPO_URL, "paper": PAPER,
    }
