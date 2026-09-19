"""
The editions framework and the Friday preview.

Uses the two-club database from test_digest so the facts layer is tested
against the same history the digest tests already trust.
"""

import datetime
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from test_digest import _fixture, _make_db  # noqa: E402

import notify  # noqa: E402
from editions import archive, config, phrasing, tone  # noqa: E402
from editions import preview as preview_mod  # noqa: E402
from editions.preview import PreviewEdition  # noqa: E402
from editions.runner import main, resolve_edition  # noqa: E402

FRIDAY = datetime.date(2026, 8, 14)


def _build(tmp_path, fixtures):
    conn = _make_db()
    return PreviewEdition(conn, FRIDAY, tmp_path / "charts").build(fixture_list=fixtures)


# ── the preview ────────────────────────────────────────────────────────────

def test_preview_renders_all_three_speeds_and_writes_claims(tmp_path):
    out = _build(tmp_path, [_fixture()])
    assert "Giant FC" in out.html and "Steady FC" in out.html
    assert config.SITE_URL in out.html  # club names link to the site
    assert out.subject.startswith("The week ahead")
    assert out.thin is None

    # One fixture is below LONG_MIN, so it is promoted to long-form anyway.
    assert [c["speed"] for c in out.claims] == ["long"]
    snap = out.claims[0]["snapshot"]["home"]
    assert snap["club_id"] == "giant-fc" and snap["position"] == 8
    assert out.claims[0]["fixture"]["date"] == "2026-08-15"  # serializable
    json.dumps(out.claims)


def test_fallen_giant_is_tagged():
    conn = _make_db()
    home = __import__("digest").club_context(conn, "giant-fc")
    away = __import__("digest").club_context(conn, "steady-fc")
    tags = preview_mod.tags_for(_fixture(), home, away, set(), {})
    assert ("fallen_giant", "Giant FC") in tags
    assert phrasing.tag_label(tags[0])  # every tag has words


def test_derby_tag_comes_from_the_catchment_model():
    conn = _make_db()
    conn.execute("CREATE TABLE club_catchment (club_id TEXT, nearest_rival_id TEXT,"
                 " nearest_rival_miles REAL)")
    conn.execute("INSERT INTO club_catchment VALUES ('giant-fc', 'steady-fc', 4.2)")
    rivals = preview_mod.nearest_rivals(conn)
    digest = __import__("digest")
    tags = preview_mod.tags_for(_fixture(), digest.club_context(conn, "giant-fc"),
                                digest.club_context(conn, "steady-fc"), set(), rivals)
    assert tags[0] == ("derby", 4.2)
    assert phrasing.tag_label(tags[0]) == "derby, 4 miles"


def test_an_empty_fixture_list_is_refused_not_sent(tmp_path):
    """Five divisions never go eight days without a fixture; an empty list
    is the file being rewritten, and one blank preview went out that way."""
    out = _build(tmp_path, [])
    assert out.refuse and "not sending" in out.refuse
    assert out.thin and "nothing to preview" in out.subject     # the page still renders
    assert out.claims == [] and out.images == []


def test_the_runner_retries_an_empty_file_and_sends_once_it_fills(sandbox, monkeypatch):
    import notify
    from editions import runner as runner_mod
    sandbox["csv"].write_text("Div,Date,Time,HomeTeam,AwayTeam\n")     # rewritten, empty
    sent = []
    monkeypatch.setattr(notify, "send_email", lambda *a, **k: sent.append(a) or "msg-1")

    def fill_the_file(seconds):
        sandbox["csv"].write_text("Div,Date,Time,HomeTeam,AwayTeam\nE2,15/08/2026,15:00,Giant FC,Steady FC\n")
    monkeypatch.setattr(runner_mod.time, "sleep", fill_the_file)
    assert main(_args(sandbox, "--retries", "2", "--retry-wait", "1")) == 0
    assert len(sent) == 1


def test_the_runner_gives_up_on_an_empty_file_without_sending(sandbox, monkeypatch):
    import notify
    from editions import runner as runner_mod
    sandbox["csv"].write_text("Div,Date,Time,HomeTeam,AwayTeam\n")
    monkeypatch.setattr(notify, "send_email", lambda *a, **k: pytest.fail("sent a blank"))
    monkeypatch.setattr(runner_mod.time, "sleep", lambda s: None)
    assert main(_args(sandbox, "--retries", "2", "--retry-wait", "1")) == 3
    assert not (sandbox["root"] / "archive").exists()
    # a dry run still writes the page for inspection, and exits clean
    assert main(_args(sandbox, "--dry-run")) == 0
    assert (sandbox["root"] / "preview" / "preview" / "index.html").exists()


def test_a_409_from_resend_counts_as_sent(sandbox, monkeypatch):
    import notify

    def refuse(*a, **k):
        raise notify.AlreadySent("key used")
    monkeypatch.setattr(notify, "send_email", refuse)
    assert main(_args(sandbox)) == 0
    marker = sandbox["root"] / "archive" / "preview" / FRIDAY.isoformat() / "sent.json"
    assert json.loads(marker.read_text())["message_id"] == "already-sent"


def test_notify_raises_already_sent_on_409(monkeypatch):
    import notify

    class _Resp:
        status_code = 409
        text = "idempotency key reused"
        def raise_for_status(self): raise AssertionError("should not reach")
        def json(self): return {}
    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: _Resp())
    for k, v in {"RESEND_API_KEY": "k", "EMAIL_TO": "a@b.c", "EMAIL_FROM": "d@e.f"}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(notify.AlreadySent):
        notify.send_email("s", "<p>h</p>", "t", [], idempotency_key="preview/2026-09-18")


def test_the_archive_is_not_gitignored():
    """An unanchored `preview/` in .gitignore once matched content/digests/preview/,
    and a sent edition was written and never committed."""
    import subprocess
    root = Path(__file__).parent.parent
    if not (root / ".git").exists():
        pytest.skip("not a git checkout")
    for path in ("content/digests/preview/2099-01-01/index.html",
                 "content/digests/preview/2099-01-01/sent.json"):
        rc = subprocess.run(["git", "check-ignore", "-q", path], cwd=root).returncode
        assert rc == 1, f"{path} is ignored"


def test_midweek_results_cover_the_four_days_before():
    conn = _make_db()
    conn.execute("INSERT INTO matches VALUES (2027, 3, '2026-08-11',"
                 " 'giant-fc', 'steady-fc', 'Giant FC', 'Steady FC', 3, 1, 'H')")
    conn.execute("INSERT INTO matches VALUES (2027, 3, '2026-08-08',"   # the weekend before: out
                 " 'steady-fc', 'giant-fc', 'Steady FC', 'Giant FC', 0, 0, 'D')")
    sections = preview_mod.midweek_results(conn, FRIDAY)
    assert len(sections) == 1 and sections[0]["division_name"] == "League One"
    assert [(r["hg"], r["ag"]) for r in sections[0]["results"]] == [(3, 1)]


def test_a_full_week_stays_under_the_size_limit(tmp_path):
    """
    Ninety fixtures across all five divisions - more than any real week -
    with every one listed and the long-form band at its cap. The whole
    point of the limit is that it is checked before anything reaches an
    inbox, so this is the check.
    """
    fixtures = []
    for n in range(90):
        f = _fixture()
        f["tier"] = 1 + n % 5
        f["division_name"] = preview_mod.TIER_NAMES[f["tier"]]
        f["date"] = FRIDAY + datetime.timedelta(days=1 + n % 4)
        fixtures.append(f)
    out = _build(tmp_path, fixtures)
    size = len(out.html.encode("utf-8"))
    assert size < config.SIZE_LIMIT, size
    assert sum(1 for c in out.claims if c["speed"] == "long") <= preview_mod.LONG_MAX
    # The text version lists every fixture in one shape; the HTML links names.
    assert out.text.count("Giant FC v Steady FC") == 90


# ── the runner ─────────────────────────────────────────────────────────────

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A disk copy of the test DB, a fixtures CSV, and redirected output roots."""
    db = tmp_path / "england.db"
    disk = sqlite3.connect(db)
    _make_db().backup(disk)
    disk.close()
    csv = tmp_path / "fixtures.csv"
    csv.write_text("Div,Date,Time,HomeTeam,AwayTeam\nE2,15/08/2026,15:00,Giant FC,Steady FC\n")
    monkeypatch.setattr(config, "PREVIEW_ROOT", tmp_path / "preview")
    monkeypatch.setattr(config, "ARCHIVE_ROOT", tmp_path / "archive")
    return {"db": db, "csv": csv, "root": tmp_path}


def _args(sandbox, *extra):
    return ["preview", "--date", FRIDAY.isoformat(), "--db-path", str(sandbox["db"]),
            "--fixtures-file", str(sandbox["csv"]), *extra]


def test_dry_run_writes_a_local_copy_and_sends_nothing(sandbox, monkeypatch):
    monkeypatch.setattr(notify, "send_email", lambda *a, **k: pytest.fail("sent"))
    assert main(_args(sandbox, "--dry-run")) == 0
    out = sandbox["root"] / "preview" / "preview"
    assert (out / "index.html").exists() and (out / "subject.txt").exists()
    assert "cid:" not in (out / "index.html").read_text(encoding="utf-8")
    assert not (sandbox["root"] / "archive").exists()


def test_a_send_archives_by_type_and_date_and_marks_itself_sent(sandbox, monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "send_email", lambda *a, **k: calls.append(a) or "msg-1")
    assert main(_args(sandbox)) == 0
    assert len(calls) == 1
    out = sandbox["root"] / "archive" / "preview" / FRIDAY.isoformat()
    assert (out / "index.html").exists() and (out / "claims.json").exists()
    assert json.loads((out / "sent.json").read_text())["message_id"] == "msg-1"
    assert json.loads((out / "claims.json").read_text())["edition"] == "preview"

    # A second run is a no-op, not a second email; --force sends again.
    assert main(_args(sandbox)) == 0 and len(calls) == 1
    assert main(_args(sandbox, "--force")) == 0 and len(calls) == 2


def test_an_oversized_edition_is_refused_before_sending(sandbox, monkeypatch):
    monkeypatch.setattr(config, "SIZE_LIMIT", 100)
    monkeypatch.setattr(notify, "send_email", lambda *a, **k: pytest.fail("sent"))
    assert main(_args(sandbox)) == 1


def test_auto_picks_the_scheduled_edition_or_nothing():
    assert resolve_edition("auto", datetime.date(2026, 9, 4)) == "preview"   # a Friday
    assert resolve_edition("auto", datetime.date(2026, 9, 5)) is None        # a Saturday
    assert resolve_edition("preview", datetime.date(2026, 9, 5)) == "preview"


def test_auto_on_an_unscheduled_day_exits_cleanly(sandbox, capsys):
    assert main(["auto", "--date", "2026-09-05", "--db-path", str(sandbox["db"])]) == 0


# ── tone ───────────────────────────────────────────────────────────────────

def test_straight_dates_apply_on_anniversaries_and_to_named_clubs():
    entries = [
        {"date": "1989-04-15", "clubs": ["liverpool-fc"], "note": "x"},
        {"clubs": ["some-fc"], "note": "undated, so always"},
        {"date": "2000-01-01", "note": "no clubs, so everyone"},
    ]
    april = datetime.date(2026, 4, 15)
    assert tone.straight(april, {"liverpool-fc"}, entries)
    assert not tone.straight(april, {"everton-fc"}, entries)
    assert not tone.straight(datetime.date(2026, 4, 16), {"liverpool-fc"}, entries)
    assert tone.straight(datetime.date(2026, 7, 7), {"some-fc"}, entries)
    assert tone.straight(datetime.date(2026, 1, 1), {"anyone-fc"}, entries)
    assert not tone.straight(datetime.date(2026, 1, 2), {"anyone-fc"}, entries)


def test_the_committed_straight_dates_file_parses():
    assert tone.load() == []   # empty until an event is added, but valid


def test_archive_dir_is_one_stream_per_edition():
    assert archive.archive_dir("preview", FRIDAY) == config.ARCHIVE_ROOT / "preview" / "2026-08-14"


def test_ordinals_are_right_past_the_twenties():
    cases = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 11: "11th", 12: "12th", 13: "13th",
             21: "21st", 22: "22nd", 23: "23rd", 24: "24th", 93: "93rd", 101: "101st",
             111: "111th", 112: "112th", None: ""}
    for n, want in cases.items():
        assert phrasing.ordinal(n) == want, n


def test_the_moved_tag_reads_the_last_completed_season():
    import digest
    conn = _make_db()
    conn.execute("UPDATE standings SET status='Relegated' WHERE club_id='giant-fc' AND season_end_year=2025")
    conn.execute("INSERT INTO standings VALUES (2026, 4, 'League Two', 'giant-fc', 'Giant FC', 3,"
                 " 5, 3, 1, 1, 8, 3, 5, 10, 'In progress', 'test')")
    tags = preview_mod.tags_for(_fixture(), digest.club_context(conn, "giant-fc"),
                                digest.club_context(conn, "steady-fc"), set(), {})
    assert ("moved", "Giant FC", "Relegated") in tags
    assert phrasing.tag_label(("moved", "Giant FC", "Relegated")) == "relegated last season"


def test_a_preview_only_flag_on_another_edition_is_refused_not_crashed(sandbox, capsys):
    rc = main(["review-top", "--date", "2026-09-07", "--dry-run", "--db-path", str(sandbox["db"]),
               "--fixtures-file", str(sandbox["csv"])])
    assert rc == 2


def test_the_send_carries_an_idempotency_key(monkeypatch, tmp_path):
    import notify
    seen = {}

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"id": "msg-42"}

    monkeypatch.setattr(notify.requests, "post",
                        lambda url, headers, json, timeout: seen.update(headers=headers) or _Resp())
    for k, v in {"RESEND_API_KEY": "k", "EMAIL_TO": "a@b.c", "EMAIL_FROM": "d@e.f"}.items():
        monkeypatch.setenv(k, v)
    assert notify.send_email("s", "<p>h</p>", "t", [], idempotency_key="preview/2026-09-18") == "msg-42"
    assert seen["headers"]["Idempotency-Key"] == "preview/2026-09-18"
    notify.send_email("s", "<p>h</p>", "t", [])
    assert "Idempotency-Key" not in seen["headers"]
