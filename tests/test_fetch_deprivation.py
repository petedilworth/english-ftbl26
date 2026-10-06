"""The deprivation fetch: header matching, the name join, the roll-up to MSOAs."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import fetch_deprivation as fd  # noqa: E402

# File 7's headers as MHCLG writes them (the 2019 file's wording, 2021 geography).
HEADER = [
    "LSOA code (2021)", "LSOA name (2021)", "Local Authority District code (2024)",
    "Local Authority District name (2024)", "Index of Multiple Deprivation (IMD) Score",
    "Index of Multiple Deprivation (IMD) Rank (where 1 is most deprived)",
    "Income Score (rate)", "Employment Score (rate)", "Education, Skills and Training Score",
    "Health Deprivation and Disability Score", "Crime Score", "Barriers to Housing and Services Score",
    "Living Environment Score", "Income Deprivation Affecting Children Index (IDACI) Score (rate)",
    "Income Deprivation Affecting Older People (IDAOPI) Score (rate)",
    "Total population: mid 2022 (excluding prisoners)",
]


def test_every_domain_is_found_in_the_header():
    cols = fd.find_columns(HEADER)
    assert cols["lsoa_code"] == "LSOA code (2021)" and cols["population"].startswith("Total population")
    assert set(fd.DOMAINS) <= set(cols)
    assert cols["imd"] == "Index of Multiple Deprivation (IMD) Score"   # not the rank column


def test_a_header_without_the_score_fails_loudly_and_shows_itself():
    with pytest.raises(SystemExit, match="LSOA code"):
        fd.find_columns(["LSOA code (2021)", "Total population: mid 2022"])


def test_the_naming_rule_joins_an_lsoa_to_its_msoa():
    names = {"E02000001": "City of London 001", "E02001234": "Bolton 012"}
    lsoa = pd.DataFrame({"lsoa_name": ["Bolton 012C", "City of London 001A", "Bolton 0129"]})
    got = fd.msoa_from_names(lsoa, names)
    assert got.tolist()[:2] == ["E02001234", "E02000001"] and pd.isna(got.iloc[2])   # no letter, no match


def test_the_roll_up_weights_by_people_and_ranks_most_deprived_first():
    lsoa = pd.DataFrame({
        "msoa_code": ["M1", "M1", "M2"], "population": [3000, 1000, 2000],
        "imd": [40.0, 0.0, 20.0], "income": [0.2, 0.0, 0.1]})
    out = fd.aggregate(lsoa, {"M1": "Poor 001", "M2": "Mid 002"}).set_index("msoa_code")
    assert out.loc["M1", "imd"] == pytest.approx(30.0)      # 3,000 people at 40 and 1,000 at 0
    assert out.loc["M1", "imd_rank"] == 1 and out.loc["M2", "imd_rank"] == 2
    assert out.loc["M1", "lsoas"] == 2 and out.loc["M1", "population"] == 4000
    assert out.loc["M1", "msoa_name"] == "Poor 001"
