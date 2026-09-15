"""The Jinja2 environment for the email templates."""

import jinja2

from editions import config

_env: jinja2.Environment | None = None

from editions.phrasing import ordinal


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
