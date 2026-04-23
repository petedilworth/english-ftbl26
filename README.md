# English Football Historical Database

SQLite database of English football league standings for Tiers 1–5 from the 1993/94 season to present. Phase 1 — historical data only.

## Data source

[football-data.co.uk](https://www.football-data.co.uk/) free CSV files (no API key required).

## Setup

```bash
pip install -r requirements.txt
```

## Run the pipeline

```bash
# Full run: download all CSVs then build the database
python src/pipeline.py

# Skip download (use already-cached CSVs)
python src/pipeline.py --skip-download

# Re-download all CSVs even if cached
python src/pipeline.py --force-download

# Limit to specific season range
python src/pipeline.py --season-start 2010 --season-end 2024
```

The pipeline prints a report of any unresolved club names at the end. Add missing entries to `club_master.csv` and re-run to resolve them.

## Project structure

```
data/
  raw/          Downloaded CSVs (never modified)
  db/
    england.db  SQLite database
src/
  download.py   Downloads CSVs from football-data.co.uk
  aggregate.py  Aggregates match results to standings
  entities.py   Manages club_master table and name resolution
  status.py     Assigns promotion/relegation status (rules in RULES dict)
  trajectory.py Builds derived club_trajectory table
  pipeline.py   Orchestrates all steps end-to-end
club_master.csv Canonical club list — manually maintained seed file
```

## Database schema

### `club_master`
Seeded from `club_master.csv`. Edit this file to add name variants or new clubs, then re-run the pipeline.

| Column | Type | Notes |
|---|---|---|
| `club_id` | TEXT PK | Permanent slug, e.g. `barnsley-fc` |
| `canonical_name` | TEXT | Current official name |
| `name_variants` | TEXT | JSON array of known source spellings |
| `lineage_parent_id` | TEXT | For successor clubs (AFC Wimbledon → Wimbledon FC) |
| `current_tier` | INT | 0 = defunct/out of scope |

### `standings`
One row per club per season.

| Column | Type | Notes |
|---|---|---|
| `season_end_year` | INT | e.g. 2024 for 2023/24 |
| `tier` | INT | 1–5 |
| `division_name` | TEXT | e.g. "Premier League", "Championship" |
| `club_id` | TEXT | NULL if name could not be resolved |
| `club_name` | TEXT | Raw name from source CSV |
| `position` | INT | Final league position |
| `points` | INT | End-of-season points total |
| `status` | TEXT | See values below |
| `source` | TEXT | e.g. `football-data.co.uk/E0/9394` |

**Status values:** `Champions` · `Promoted` · `Play-off Promoted` · `Stayed` · `Play-off Relegated` · `Relegated`

### `club_trajectory`
Derived table — rebuilt on every pipeline run.

| Column | Type |
|---|---|
| `club_id` | TEXT PK |
| `canonical_name` | TEXT |
| `current_tier` | INT |
| `current_tier_streak` | INT |
| `highest_tier` | INT |
| `lowest_tier` | INT |
| `seasons_in_tier1` | INT |
| `last_tier1_season` | INT |
| `first_season_in_db` | INT |
| `last_season_in_db` | INT |
| `total_promotions` | INT |
| `total_relegations` | INT |
| `yo_yo_score` | REAL |

## Adjusting promotion/relegation rules

All cutoff rules live in `src/status.py` in the `RULES` dict. Each key is `(tier, season_end_from, season_end_to_inclusive)`. To change rules for a specific season range, add a new entry — the most recently applicable rule (highest `season_end_from`) takes precedence.

## Maintaining `club_master.csv`

- Add a new row for any club that appears in the unresolved name report
- Add the unrecognised spelling to the `name_variants` JSON array of the correct club
- `club_id` values are permanent — never change them once assigned
- Set `current_tier=0` for defunct clubs
- Set `lineage_parent_id` for re-formed clubs (e.g. AFC Wimbledon → `wimbledon-fc`)

## Useful queries

```sql
-- Top yo-yo clubs
SELECT canonical_name, yo_yo_score, total_promotions, total_relegations
FROM club_trajectory
ORDER BY yo_yo_score DESC
LIMIT 10;

-- Clubs unresolved in standings
SELECT DISTINCT club_name, season_end_year, tier
FROM standings
WHERE club_id IS NULL
ORDER BY season_end_year, tier;

-- Full history for one club
SELECT season_end_year, tier, division_name, position, points, status
FROM standings
WHERE club_id = 'sunderland-afc'
ORDER BY season_end_year;
```
