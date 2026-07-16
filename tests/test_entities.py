import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from entities import build_resolver, resolve_name, seed_club_master

HEADER = "club_id,canonical_name,name_variants,lineage_parent_id,current_tier\n"
ROW_A = 'a-fc,Alpha,"[""Alpha"",""Alpha FC""]",,1\n'
ROW_B = 'b-fc,Beta,"[""Beta""]",,2\n'


def _write_csv(path, rows):
    path.write_text(HEADER + "".join(rows), encoding="utf-8")


def test_seed_and_resolve(tmp_path):
    csv = tmp_path / "cm.csv"
    _write_csv(csv, [ROW_A, ROW_B])
    conn = sqlite3.connect(":memory:")
    seed_club_master(conn, csv)
    resolver = build_resolver(conn)
    assert resolve_name("alpha fc", resolver) == "a-fc"
    assert resolve_name("  Beta  ", resolver) == "b-fc"
    assert resolve_name("Unknown Town", resolver) is None


def test_stale_rows_are_pruned(tmp_path):
    csv = tmp_path / "cm.csv"
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE standings (season_end_year INT, tier INT, club_id TEXT,"
        " club_name TEXT)"
    )

    # First seed with both clubs; standings references b-fc
    _write_csv(csv, [ROW_A, ROW_B])
    seed_club_master(conn, csv)
    conn.execute("INSERT INTO standings VALUES (2024, 2, 'b-fc', 'Beta')")

    # Re-seed with b-fc removed (e.g. hand-added entry superseded upstream)
    _write_csv(csv, [ROW_A])
    seed_club_master(conn, csv)

    ids = {r[0] for r in conn.execute("SELECT club_id FROM club_master")}
    assert ids == {"a-fc"}
    # Reference was detached, row not dropped
    row = conn.execute("SELECT club_id, club_name FROM standings").fetchone()
    assert row == (None, "Beta")

    resolver = build_resolver(conn)
    assert resolve_name("Beta", resolver) is None


def test_resolution_normalizes_invisible_characters(tmp_path):
    csv = tmp_path / "cm.csv"
    _write_csv(
        csv,
        ['kings-lynn-town-fc,King\'s Lynn Town,"[""Kings Lynn"",""King\'s Lynn""]",,5\n'],
    )
    conn = sqlite3.connect(":memory:")
    seed_club_master(conn, csv)
    resolver = build_resolver(conn)
    assert resolve_name("Kings Lynn", resolver) == "kings-lynn-town-fc"
    assert resolve_name("Kings  Lynn", resolver) == "kings-lynn-town-fc"  # double space
    assert resolve_name("Kings\xa0Lynn", resolver) == "kings-lynn-town-fc"  # NBSP
    assert resolve_name("Kings​Lynn", resolver) == "kings-lynn-town-fc"  # ZWSP as separator
    assert resolve_name("King​s Lynn", resolver) == "kings-lynn-town-fc"  # ZWSP inside word
    assert resolve_name("﻿Kings Lynn", resolver) == "kings-lynn-town-fc"  # BOM prefix
    assert resolve_name("King’s Lynn", resolver) == "kings-lynn-town-fc"  # curly apostrophe
    assert resolve_name(" kings lynn ", resolver) == "kings-lynn-town-fc"


def test_season_override_wimbledon(tmp_path):
    csv = tmp_path / "cm.csv"
    _write_csv(
        csv,
        [
            'wimbledon-fc,Wimbledon FC,"[""Wimbledon""]",,0\n',
            'mk-dons-fc,MK Dons,"[""MK Dons""]",,3\n',
        ],
    )
    conn = sqlite3.connect(":memory:")
    seed_club_master(conn, csv)
    resolver = build_resolver(conn)
    assert resolve_name("Wimbledon", resolver, 2003) == "wimbledon-fc"
    assert resolve_name("Wimbledon", resolver, 2004) == "mk-dons-fc"
