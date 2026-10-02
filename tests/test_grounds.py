"""Who owns the ground: the record, how it scores, and the page."""

import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import grounds  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cache():
    grounds._cache.clear()
    yield
    grounds._cache.clear()


def _write(tmp_path, entries):
    path = tmp_path / "grounds.yml"
    path.write_text(yaml.safe_dump({"researched": "October 2026", "grounds": entries}), encoding="utf-8")
    return path


def test_merge_adds_the_record_and_keeps_the_old_field_in_step(tmp_path):
    path = _write(tmp_path, {
        "giant-fc": {"owner_type": "owner_company", "owner_name": "Owner Holdings"},
        "steady-fc": {"owner_type": "council", "disputed": True},
        "broken-fc": {"owner_type": "somebody"},
    })
    facts = grounds.merge("giant-fc", {"stadium_ownership": "club", "capacity": 9000}, path)
    assert facts["ground"]["owner_name"] == "Owner Holdings"
    assert facts["stadium_ownership"] == "third_party"      # the research overrides the old word
    assert facts["capacity"] == 9000
    assert grounds.merge("steady-fc", {}, path)["stadium_ownership"] == "disputed"
    assert grounds.merge("broken-fc", {"x": 1}, path) == {"x": 1}   # an invalid entry is skipped
    assert grounds.researched(path) == "October 2026"


@pytest.mark.parametrize("entry, score", [
    ({"owner_type": "club"}, 1.0),
    ({"owner_type": "council", "lease_end": 2125}, 0.75),     # 99 years left
    ({"owner_type": "council", "lease_end": 2046}, 0.5),      # 20 years left
    ({"owner_type": "council"}, 0.35),                        # length unknown: assume short
    ({"owner_type": "landlord", "lease_end": 2028}, 0.2),
    ({"owner_type": "owner_company"}, 0.4),                   # a buyer of the club doesn't get it
    ({"owner_type": "other_club"}, 0.1),
    ({"owner_type": "club", "disputed": True}, 0.0),
    ({"owner_type": "unknown"}, None),
    (None, None),
])
def test_security_scores_how_safely_a_club_holds_its_home(entry, score):
    assert grounds.security(entry, 2026) == score


def test_describe_says_who_and_for_how_long():
    assert grounds.describe({"owner_type": "council", "owner_name": "Town Council", "lease_end": 2128}, 2026) \
        == "Council-owned: Town Council; lease to 2128"
    assert grounds.describe({"owner_type": "landlord", "lease_end": 2020}, 2026).endswith("lease to 2020 – expired")
    assert grounds.describe({"owner_type": "club", "owner_name": "Giant FC Ltd"}, 2026) == "Owned by the club"


def test_the_page_builds_with_the_tier_bars_and_the_owner_apart_list(tmp_path, monkeypatch):
    import shutil

    import site_build as sb
    from site_build import SiteBuilder
    from test_digest import _make_db

    disk = tmp_path / "england.db"
    src = _make_db()
    src.commit()
    dst = sqlite3.connect(disk); src.backup(dst); dst.close()

    content_dir = tmp_path / "content"
    (content_dir / "insights").mkdir(parents=True)
    (content_dir / "insights" / "grounds.md").write_text("Who holds the deeds.\n", encoding="utf-8")
    _write(content_dir, {
        "giant-fc": {"ground": "Giant Park", "owner_type": "owner_company", "owner_name": "Owner Holdings",
                     "since": 2019, "note": "Sold to the owner's company.", "sources": ["https://example.org/a"],
                     "confidence": "high"},
        "steady-fc": {"ground": "Steady Lane", "owner_type": "council", "lease_end": 2031,
                      "owner_name": "Steady Council", "sources": ["https://example.org/b"], "confidence": "medium"},
    })
    (content_dir / "giant-fc.md").write_text("---\nfounded: 1900\n---\n", encoding="utf-8")
    shutil.copytree(Path(__file__).parent.parent / "templates", tmp_path / "templates")
    shutil.copytree(Path(__file__).parent.parent / "static", tmp_path / "static")
    monkeypatch.setattr(sb, "PROJECT_ROOT", tmp_path)
    out = tmp_path / "site"
    SiteBuilder(disk, out, charts_enabled=False).build()

    page = (out / "insights" / "grounds" / "index.html").read_text(encoding="utf-8")
    assert "Who holds the deeds." in page
    assert "Sell the club, keep the ground" in page and "Sold to the owner&#39;s company." in page
    assert 'data-type="owner_company"' in page and 'data-type="council"' in page
    assert "Leases running out" in page and "2031" in page
    assert "https://example.org/b" in page
    team = (out / "team" / "giant-fc" / "index.html").read_text(encoding="utf-8")
    assert "Owned by the owner, not the club: Owner Holdings" in team
    assert "Who owns the ground" in (out / "insights" / "index.html").read_text(encoding="utf-8")
