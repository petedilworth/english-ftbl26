"""
The placement script has to keep running.

It stopped: `scripts/place_clubs.py` imported `roster`, and src/roster.py
was deleted when the tier-6/7 roster folded into club_master. Nothing
imports the script, so nothing noticed - it raised ModuleNotFoundError on
every invocation for as long as it took anyone to run it again. A script
with no test is a script that has already broken.
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "place_clubs.py"


def _a_club_without_a_coordinate() -> str:
    """
    A club the placement script would still consider.

    These tests used to name Whitby Town and Leiston, both of which have
    a coordinate now that their Wikipedia infobox was imported - at which
    point the script refuses them for "already has a coordinate" and the
    test was checking the wrong refusal. Pick one from the data instead.
    """
    import sqlite3
    db = PROJECT_ROOT / "data" / "db" / "england.db"
    if not db.exists():
        return "a-club-that-does-not-exist"
    row = sqlite3.connect(db).execute(
        "SELECT club_id FROM club_master WHERE latitude IS NULL"
        " ORDER BY club_id LIMIT 1").fetchone()
    return row[0] if row else "a-club-that-does-not-exist"


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, cwd=PROJECT_ROOT)


def test_the_script_still_imports():
    assert SCRIPT.exists()
    result = _run("--help")
    assert result.returncode == 0, result.stderr
    assert "place" in result.stdout


def test_it_refuses_an_authority_too_wide_to_stand_in_for_a_town(tmp_path):
    """
    The threshold is the whole point: a club placed at the centroid of a
    large rural authority is in no particular town, and its people get
    handed to the wrong neighbours. North Yorkshire spreads 36 miles.
    """
    listing = tmp_path / "clubs.tsv"
    listing.write_text(f"{_a_club_without_a_coordinate()}\tNorth Yorkshire\n",
                       encoding="utf-8")
    result = _run("place", str(listing))
    assert result.returncode == 0, result.stderr
    assert "UNPLACED" in result.stderr
    assert "too wide" in result.stderr
    # Header only: nothing was placed.
    assert len([l for l in result.stdout.splitlines() if l.strip()]) == 1


def test_it_refuses_an_authority_that_does_not_exist(tmp_path):
    listing = tmp_path / "clubs.tsv"
    listing.write_text(f"{_a_club_without_a_coordinate()}\tNot A Real Authority\n",
                       encoding="utf-8")
    result = _run("place", str(listing))
    assert result.returncode == 0, result.stderr
    assert "no such authority" in result.stderr
