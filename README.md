# English Football Historical Database

SQLite database of English football league standings — Tiers 1–4 from 1958/59 and Tier 5 from 2005/06, through to the present, plus a weekly fixture-preview email digest and a static website.

## The website (Phase 3)

`src/site_build.py` renders the whole database into a static site (`site/`), deployed to GitHub Pages by `.github/workflows/deploy-site.yml` — weekly after the digest updates the data, and on any push that changes content or code.

Pages: home (current season snapshot) · one page per season · one page per division · teams index with live search, A–Z and by-division listings · a page per club (kit-color header, key stats, position-history chart, season-by-season record, and a narrative section) · interactive trajectory chart (compare any clubs) · the Matrix (every division × every season, tap a club to highlight its journey) · four insights pages (yo-yo clubs, fallen giants & risers, records & extremes, timeline) · the Groundhop Map (all 162 grounds, season slider, story filters, postcode distances) · an archive of the weekly digests.

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
  finances.py   Loads club_finances from CSV (accounts data)
  pipeline.py   Orchestrates all steps end-to-end
club_master.csv Canonical club list — manually maintained seed file
club_finances.csv Club accounts by season — manually maintained seed file
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

### `club_finances`
Seeded from `club_finances.csv`, keyed `(club_id, season_end_year)`. Unlike
the story front-matter fields, this covers **every club regardless of whether
its story has been written**, so the financial charts aren't limited to the
~50 clubs with a `content/*.md` file.

Figures come from statutory accounts filed at **Companies House**, which is
Crown copyright published under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
and so may be republished with attribution. **Nothing here is an estimate.**
Player-salary aggregators (Capology, FBref's wage pages, Transfermarkt) are
deliberately not used: their terms forbid republication, and their figures are
estimates and a different quantity from the accounts.

| Column | Notes |
|---|---|
| `disclosure` | `full` · `small_company` · `not_filed` · `dissolved` |
| `turnover`, `staff_costs` | Whole pounds; blank when not disclosed |
| `staff_costs_definition` | `excl_amortisation` · `incl_amortisation` |
| `revenue_matchday/broadcast/commercial` | Segmental note, where given |
| `profit_before_tax`, `net_debt` | Whole pounds; may be negative |
| `company_number`, `entity_name`, `consolidation_level` | Which entity filed |
| `period_start`, `period_end`, `period_months` | The actual accounting period |
| `source_url`, `filing_date`, `flags` | Provenance; `flags` is a JSON array |

Three things are recorded per row because they silently corrupt the data
otherwise:

- **"Wages" is ambiguous by 20–40%.** The staff-costs note covers all
  employees and excludes amortisation of transfer fees; some sources include
  it. `staff_costs_definition` says which a row holds.
- **Which entity filed changes the answer.** A holding company consolidating
  a stadium or media arm reports different revenue from the club company, and
  insolvency starts a new company number, breaking a series mid-window.
- **Not every period is 12 months.** Year-end changes produce 13-month periods
  that inflate costs against unchanged revenue; `period_months` surfaces it.

Non-disclosure is stored as a **state, not a null** — a club declining to
publish its turnover is itself a finding, and roughly a third of League One
and League Two clubs file under the small-company regime. Rows that
contradict themselves (a non-disclosing club carrying figures, or staff costs
with no definition) are rejected at load with a warning rather than imported.

**Current coverage and provenance.** The table now covers every tier this
database tracks — Premier League, Championship, League One, League Two
and the National League — for 2023/24 and 2024/25 (172 rows: the 20
Premier League clubs each season, plus every lower-tier club for the
season(s) it wasn't already covered by a higher tier that year). Every
figure is **press-reported** — a journalist read the filed account and
published the number — rather than read from the filing directly, so each
row carries a `press_reported` flag alongside its `source_url`. Figures
were cross-referenced across outlets before entry; where sources
conflicted irreconcilably the field was left blank rather than guessed,
which is why Aston Villa (2023/24) and Bournemouth (both seasons) have no
wage bill. Sheffield Wednesday's 2024/25 season is recorded as `not_filed`
— the club entered administration in October 2025 and its accounts are
genuinely overdue.

Disclosure gets thinner every tier down, and the National League — the
level below the EFL — is the thinnest of all: only 9 of the 48 targeted
club-seasons yielded anything usable, the lowest hit rate of any batch.
Club-seasons where research couldn't confirm even the disclosure state
itself get **no row at all**, rather than a `full` disclosure with blank
figures — a `full` row with nothing in it would misreport as "disclosed"
in the finance charts' provenance line. This tier surfaced a specific new
way that judgement call comes up: "Total exemption full accounts" is a
genuine Companies House filing category, but it denotes *audit*
exemption, not the absence of a P&L the way "abridged" or "micro-entity"
does — several clubs were initially read as `small_company` off that
label alone with zero figures either way to confirm it, and were left out
entirely rather than risk mislabeling the field. Notts County's 2023/24
season (League Two) remains the one confirmed `small_company` case.
Ebbsfleet United's 2023/24 season is `full` despite the club's own
statutory accounts omitting the P&L for the second year running — the
figures came from the club's voluntary pre-emptive statement to press
ahead of the filing, not from the filing itself, which the
`disclosed_via_statement_not_filed_accounts` flag records. Other flags in
use:

| Flag | Meaning |
|---|---|
| `press_reported` | Sourced from reporting on the filing, not the filing itself |
| `non_12_month_period` | Accounting period isn't 12 months (see `period_months`) |
| `profit_label_uncertain` | Sources disagree whether the figure is pre- or post-tax |
| `figure_disputed` | Outlets report materially different values |
| `staff_costs_disputed_omitted` | Wage bill deliberately left blank |
| `staff_costs_basis_uncertain` | A wage figure is given but its excl./incl.-amortisation basis isn't confirmed |
| `profit_includes_one_off_related_party_gain` | Result flattered by an intra-group disposal |
| `profit_includes_one_off_exceptional_gain` | Result flattered by a non-recurring item outside normal trading (e.g. litigation settlement, debt forgiveness) |
| `loss_includes_one_off_exceptional_charge` | Result worsened by a non-recurring item outside normal trading |
| `profit_figure_omitted` | Loss/profit deliberately left blank — sources disagreed on which measure (pre-tax, post-tax, stadium-cost-adjusted) applies |
| `turnover_may_include_transfer_fees` | Source itself flags that the reported "turnover" may not be pure trading revenue |
| `disclosed_via_statement_not_filed_accounts` | Figures came from the club's own public statement, not the statutory filing (which omitted the P&L) |

This is the last tier the database tracks (Tiers 1–5); extending coverage
further would mean tracking clubs below the pyramid this project follows,
not just adding rows to the existing schema.

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
