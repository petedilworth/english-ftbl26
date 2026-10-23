"""The Wikipedia check: words, shared runs, finding the article, the report."""

import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import check_wikipedia_overlap as cw  # noqa: E402

ARTICLE = ("Test Town Football Club is an English football club based in Testford. Founded in 1905 by workers "
           "at the Singer cycle factory, the club moved to London Road in 1934 and was elected to the Football "
           "League in 1960 after a long campaign by its supporters and the local council.")


def test_words_drop_markup_and_keep_apostrophes():
    assert cw.words("The club's [ground](https://x.example) – London Road’s end.") == [
        "the", "club's", "ground", "london", "road's", "end"]


def test_shares_and_copied_runs():
    story = cw.words("Founded in 1905 by workers at the Singer cycle factory, the club moved to London Road in 1934. "
                     "Nobody remembers why the colours are blue.")
    article = cw.words(ARTICLE)
    assert cw.share(story, cw.grams(article, 5), 5) > 0.5
    runs = cw.common_runs(story, article)
    assert runs and runs[0][0] == 18 and runs[0][1].startswith("founded in 1905 by workers")
    assert cw.longest_run(story, article) == 18
    assert cw.common_runs(cw.words("Nobody remembers why the colours are blue at all, they say."), article) == []


def _fake_wiki(pages: dict[str, str], search: list[str] = ()):
    """A stand-in for the API: extracts by title (redirects ignored), and a fixed search result."""
    def get(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        if q.get("list") == "search":
            return json.dumps({"query": {"search": [{"title": t} for t in search]}})
        title = q["titles"]
        if title in pages:
            return json.dumps({"query": {"pages": [{"title": title, "extract": pages[title]}]}})
        return json.dumps({"query": {"pages": [{"title": title, "missing": True}]}})
    return get


def test_find_article_tries_the_likely_titles_then_search():
    get = _fake_wiki({"Test Town F.C.": ARTICLE})
    assert cw.find_article("Test Town", get)[0] == "Test Town F.C."
    # A disambiguation page is not the club, and search finds the article.
    get = _fake_wiki({"Test Town F.C.": "Test Town F.C. may refer to: one football club or another.",
                      "Test Town A.F.C. (1905)": ARTICLE}, search=["Test Town A.F.C. (1905)"])
    assert cw.find_article("Test Town", get)[0] == "Test Town A.F.C. (1905)"
    assert cw.find_article("Nowhere", _fake_wiki({})) is None


def test_story_text_takes_prose_and_long_notes(tmp_path):
    path = tmp_path / "test-town-fc.md"
    path.write_text("---\nfounded: 1905\nnickname: the Testers\nrivalries:\n  - opponent: other-fc\n"
                    "    note: A dispute over the ground in 1934 that neither side has ever quite let go of.\n"
                    "sources:\n  - https://example.org/a-long-url-that-is-not-prose\n---\n"
                    "## Origins\nFounded by factory workers.\n", encoding="utf-8")
    text = cw.story_text(path)
    assert "Founded by factory workers." in text and "A dispute over the ground in 1934" in text
    assert "the Testers" not in text and "example.org" not in text


def test_the_report_has_a_row_per_club(tmp_path):
    get = _fake_wiki({"Test Town F.C.": ARTICLE})
    out = tmp_path / "overlap.tsv"
    story = "Founded in 1905 by workers at the Singer cycle factory, the club moved to London Road in 1934."
    rows = cw.run([("test-town-fc", "Test Town", story), ("lost-fc", "Lost", "A story with no article at all.")],
                  get, out, pause=0)
    assert rows[0]["article"] == "Test Town F.C." and rows[0]["url"] == "https://en.wikipedia.org/wiki/Test_Town_F.C."
    assert rows[0]["longest"] >= cw.COPIED and rows[0]["passages"].startswith("founded in 1905")
    assert rows[1]["article"] == "" and rows[1]["club_id"] == "lost-fc"
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("#") and lines[2].split("\t")[:2] == ["club_id", "article"]
    assert len(lines) == 5
