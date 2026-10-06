"""The Sources page: every page listed, every source real, every link built."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import sources  # noqa: E402

ROOT = Path(__file__).parent.parent


def test_every_page_names_sources_that_exist():
    for _section, rows in sources.PAGES:
        for title, _path, keys, _note in rows:
            assert keys, title
            assert set(keys) <= set(sources.SOURCES), (title, set(keys) - set(sources.SOURCES))


def test_every_source_is_used_and_fully_described():
    used = sources.used_by()
    for key, src in sources.SOURCES.items():
        assert used[key], f"{key} is on no page"
        for field in ("name", "url", "what", "licence", "refresh"):
            assert src.get(field), (key, field)
        assert src["url"].startswith("https://")


def test_every_insight_story_with_prose_is_on_the_sources_page():
    # The insight index links a story for each prose file; each must appear here.
    listed = {p for _s, rows in sources.PAGES for _t, p, _k, _n in rows}
    for md in (ROOT / "content" / "insights").glob("*.md"):
        slug = md.stem
        if slug in {"points-eras", "safe-thresholds", "the-drop", "the-rise", "the-pyramid"}:
            continue   # covered together by the league-record row
        assert f"insights/{slug}/index.html" in listed, f"{slug} has no sources entry"


def test_the_built_page_links_only_to_pages_that_exist():
    site = ROOT / "site"
    page = site / "sources" / "index.html"
    if not page.exists():
        import pytest
        pytest.skip("site not built")
    html = page.read_text(encoding="utf-8")
    for href in re.findall(r'href="\.\./([^"#]+)', html):
        assert (site / href).exists(), href
    assert html.count('class="sources-card"') == len(sources.SOURCES)
