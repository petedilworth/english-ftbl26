# English Football Historical Database

SQLite database of English football league standings for Tiers 1–5 from the 1993/94 season to present, plus a weekly fixture-preview email digest and a static website.

## The website (Phase 3)

`src/site_build.py` renders the whole database into a static site (`site/`), deployed to GitHub Pages by `.github/workflows/deploy-site.yml` — weekly after the digest updates the data, and on any push that changes content or code.

Pages: home (current season snapshot) · one page per season · one page per division · teams index with live search, A–Z and by-division listings · a page per club (kit-color header, key stats, position-history chart, season-by-season record, and a narrative section).

**Enable it once:** repo Settings → Pages → Source: **GitHub Actions**. Then run the "Deploy Site" workflow (or push to main).

**Club narratives:** write `content/<club_id>.md` (see `content/README.md`); the club's page picks it up on the next deploy.

**Local preview:**
```bash
python src/site_build.py && python -m http.server -d site 8000
```

## Weekly digest (Phase 2)

Every Monday a GitHub Actions workflow (`.github/workflows/weekly-digest.yml`):
1. Refreshes the current season's results and rebuilds standings/trajectory
2. Fetches the coming week's fixtures from football-data.co.uk
3. Picks the most interesting matches (storyline scoring: fallen giants, yo-yo clubs, top-of-table clashes, followed clubs) and writes a narrative + stats preview for each, with an embedded two-club position-history chart and head-to-head record since 1993
4. Emails the digest via [Resend](https://resend.com) and commits the updated `england.db` back to the repo

### One-time setup
1. Add three repository secrets (Settings → Secrets and variables → Actions):
   `RESEND_API_KEY`, `EMAIL_TO`, `EMAIL_FROM` (same values as your other Resend project)
2. Run the workflow manually once with **full_rebuild = true** (Actions tab → Weekly Digest → Run workflow) to build and commit the database
3. Optionally set a `FOLLOWED_CLUBS` env var (comma-separated club_id slugs) in the workflow, or edit `FOLLOWED_CLUBS` in `src/digest.py` — those clubs are always featured

### Local preview
```bash
python src/digest.py --dry-run   # writes preview/digest_preview.html, sends nothing
```

## Phase 1 — the database

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

Note: SSL certificate verification is disabled for football-data.co.uk downloads — the site's certificate chain trips some Windows/Anaconda setups. This is limited to that one known host.

## Run the tests

```bash
python -m pytest tests/
```

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
| `current_tier` | INT | Informational only — not used by the pipeline. `club_trajectory.current_tier` is computed from each club's most recent `standings` row instead, so it never goes stale. |

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

Statuses are first assigned by league position using the rules config, then **reconciled against the club's actual tier the following season** — so `Play-off Promoted` means the club actually won the play-offs, not just qualified. The latest season keeps provisional positional statuses (play-off eligibility) until next season's data exists. The table also stores `played, won, drawn, lost, gf, ga, gd` per club-season.

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
