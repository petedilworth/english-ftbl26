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
    listing.write_text("whitby-town-fc\tNorth Yorkshire\n", encoding="utf-8")
    result = _run("place", str(listing))
    assert result.returncode == 0, result.stderr
    assert "UNPLACED whitby-town-fc" in result.stderr
    assert "too wide" in result.stderr
    # Header only: nothing was placed.
    assert len([l for l in result.stdout.splitlines() if l.strip()]) == 1


def test_it_refuses_an_authority_that_does_not_exist(tmp_path):
    listing = tmp_path / "clubs.tsv"
    listing.write_text("leiston-fc\tNot A Real Authority\n", encoding="utf-8")
    result = _run("place", str(listing))
    assert result.returncode == 0, result.stderr
    assert "no such authority" in result.stderr
