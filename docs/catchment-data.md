# Catchment data — what to download and where to put it

`src/catchment.py` needs one file at the repo root: **`msoa_demographics.csv`**.
It is not committed, because this environment's network policy blocks
`ons.gov.uk` and `geoportal.statistics.gov.uk` at the proxy, so the data
could not be fetched here. The code runs without it — `seed_msoa_demographics`
logs and returns 0, `club_catchment` stays empty, and the catchment charts
render nothing rather than something wrong.

Assembling it is a short manual job for anyone with an unblocked browser.

## The three sources

All ONS, all Open Government Licence v3.0, all free to republish with
attribution — the same licence basis as `club_finances.csv`.

| Piece | Dataset | Join key |
|---|---|---|
| Centroids | *Middle layer Super Output Areas (Dec 2021) EW Population Weighted Centroids* — ONS Open Geography Portal | `MSOA21CD` |
| Population | *Mid-year population estimates by MSOA* — ONS | `MSOA21CD` |
| Income | *Income estimates for small areas, England and Wales* — ONS, net annual household income | `MSOA21CD` |

Filter to England (`MSOA21CD` starting `E`) — about **6,800 rows**, roughly
400KB. The repo already commits a 15MB database, so size is not a concern.

## The columns the loader expects

Required: `msoa_code`, `latitude`, `longitude`, `population`.
Optional but wanted: `msoa_name`, `local_authority`, `population_year`,
`net_income`, `net_income_year`, `income_ci_lower`, `income_ci_upper`,
`source_url`.

Centroids must be **WGS84 latitude/longitude**, not British National Grid
eastings and northings. The portal offers both; taking the wrong one puts
every club in the North Sea, and the loader will reject the rows as outside
England rather than quietly mapping them.

## Why the income confidence interval is a required habit, not a nicety

ONS small-area income is **modelled, not measured**. It is a statistical
estimate for an area too small to survey directly, and its confidence
intervals are wide — often ±15% or more. The loader carries
`income_ci_lower` and `income_ci_upper` and rejects any row whose central
estimate falls outside its own interval, because that combination means the
join went wrong.

Nothing should ever be ranked on income alone, and any page showing it must
show the interval too.

## Verifying it landed correctly

```bash
python3 src/pipeline.py --season-start 1959 --skip-download
python3 -c "
import sqlite3; c = sqlite3.connect('data/db/england.db')
print(c.execute('SELECT COUNT(*), SUM(population) FROM msoa_demographics').fetchone())
print(c.execute('SELECT COUNT(*) FROM club_catchment').fetchone())
"
```

England's population is about **57 million**. If the sum is far off that,
the population column is the wrong vintage or the wrong geography.

Then run the honesty check in `tests/test_catchment.py` — in particular
`test_isolation_alone_earns_nothing`, which is there to catch the model
degenerating into a ranking of emptiness.

## Once it lands

```bash
python3 src/prospects.py          # the ranked screen
```

Until then that command prints `NOT RANKED` and the candidate list with
every input marked missing, which is the intended behaviour: ceiling and
fall alone would rank on nostalgia, and nostalgia is the half of the
thesis that is free.

Two exclusions the screen applies before ranking, both reported with
counts and reasons rather than applied silently:

- **A club whose identity has been carried on by a successor.** What an
  investor would be buying has already moved. Detected from
  `club_master.lineage_parent_id`, not from names.
- **A club absent for more than 25 seasons** (`STALE_AFTER_SEASONS`).
  Workington left the Football League in 1977 and are 50 seasons gone;
  their catchment is the most uncontested in the data and their supporters
  are not. The threshold is judgement and it is a constant so it can be
  argued with.
