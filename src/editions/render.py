"""The Jinja2 environment for the email templates."""

import jinja2

from editions import config

_env: jinja2.Environment | None = None

ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 21: "21st", 22: "22nd", 23: "23rd", 24: "24th"}


def ordinal(n: int | None) -> str:
    if n is None:
        return ""
    return ORDINALS.get(n, f"{n}th")


def env() -> jinja2.Environment:
    global _env
    if _env is None:
        _env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(config.TEMPLATE_DIR)),
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        _env.filters["ordinal"] = ordinal
        _env.filters["club_url"] = config.club_url
        _env.globals["site_url"] = config.SITE_URL
    return _env


def render(template: str, **ctx) -> str:
    return env().get_template(template).render(**ctx)
