<!--
Status: PAUSED before any implementation. Nothing in this plan has been
built. Written 2026-08-25 against main @ 43adc58.

Every file path, line number and code claim below was verified against the
repository at that commit. They will drift — re-check before acting on
them, and treat the reasoning as the durable part.
-->

# Adding tier 6 — an N-division tier

## Context

The site covers tiers 1–5 from 1993/94. Tier 6 is the first level that is
**not one division**: National League North and South from 2004/05, and
before that three parallel feeder leagues — Northern Premier, Isthmian and
Southern League Premier. So the model to build is "a tier has one or more
divisions", under which every existing tier is a 1-division tier and tiers
1–5 barely change.

Three decisions are already taken:

1. **Data source: hand-curated final tables.** football-data.co.uk
   publishes `E0`–`E3` and `EC` and stops at tier 5; there is no free
   match-level feed below it. Tier 6 gets `standings` rows and **no
   `matches` rows**, by design.
2. **Coverage: full history, 1993/94 onward.**
3. **Scope: tier 6 is first-class** — division pages, season tables,
   matrix, map, charts, insights, colours.

**The honest headline: the code is 2–3 days, the data is weeks.** Roughly
2,000 curated standings rows and ~200 new clubs in `club_master.csv`, each
needing a permanent id, name variants and ideally a ground. The sequencing
below is built around that, not around the code.

## The one part worth reconsidering

The 1993/94–2003/04 era (Stage 4C) is the part I'd push back on. Those
three leagues were not really one division of English football: their
champions did not all go up, they shared a promotion slot into the
Conference decided partly off the pitch, and their sizes drifted. The
site's grammar — one continuous ladder, an "overall position", a
rectangular tier × season matrix — asserts a uniformity that era lacked,
and the matrix would gain three rows populated for 11 columns and blank for
22, which reads as missing data rather than "this structure didn't exist".

It is in scope as decided. When Stage 4C is reached, decide
deliberately whether to suppress era-1 tier-6 rows from the trajectory
chart and records tables — the same principle the codebase already applies
to incomplete tables. My recommendation is yes; the division pages and
season tables carry the history perfectly well without asserting a ladder.

## A note on the tier-5 backfill

The tier-5 backfill is required for coherence **only because of the
full-history choice**. Stage 4A alone (NL North/South
from 2005/06) creates *no* hole at all, because tier 5 already starts
2005/06 — every tier-6 season would have a tier-5 season above it. The
backfill is a hard precondition of Stage 4C specifically. If you ever
descope to 4A, it becomes optional.

---

## The data model

Add `division_id TEXT` to `standings` and `matches`. `tier` stays — it is
the *level*, which is what the ladder, charts and `level.py` actually mean.
`division_name` stays as the derived display string.

**No table rebuild.** The existing `UNIQUE(season_end_year, tier,
club_name)` (`src/pipeline.py:60`) is still satisfiable: no club appears
twice in one tier in one season, even with parallel divisions. So this is
an `ALTER TABLE ... ADD COLUMN` plus a new unique index, handled by the
existing `pipeline._migrate_standings_columns()` (`src/pipeline.py:80-87`),
which already does exactly this for the stat columns. The committed
`england.db` is never at risk from a `CREATE/INSERT/DROP/RENAME` dance.

`division_id` **is the existing URL slug** for tiers 1–5, so backfill is
one `UPDATE ... WHERE tier = ?` per tier and **zero URLs change**:

| tier | `division_id` | years |
|---|---|---|
| 1–5 | `premier-league`, `championship`, `league-one`, `league-two`, `national-league` | all |
| 6 | `northern-premier-league-premier`, `isthmian-league-premier`, `southern-league-premier` | 1994–2004 |
| 6 | `national-league-north`, `national-league-south` | 2005– |

It deliberately does not encode era renames — "First Division" →
"Championship" stays in the display-name lookup, which is what keeps
`/division/championship/` covering 1993/94 onward.

### `src/divisions.py` — one registry, replacing five hardcoded tables

`Division(division_id, tier, first_year, last_year, sort_order, names,
slug, source_code)`. Re-point at it: `aggregate.DIVISION_NAMES:17-23`,
`site_build.TIER_SLUGS:33-39`, `download.TIER_TO_CODE:25`,
`fixtures.DIV_TO_NAME:29-35`. `charts.TIER_COLORS:34-40` and
`level.TIER_NAMES:58-64` stay **tier**-keyed (they describe level, not
division) but should be generated from the registry so a tier can't be
added in one place and forgotten in another. Tier-6 divisions carry
`source_code = None`, which is also how `download.download_all` learns not
to try fetching them.

Not a DB table — nothing needs to SQL-join against division metadata, and a
table would be a fifth thing to keep in sync.

### The DELETE bug — the single most important line

`src/pipeline.py:276-278` and `291-294` delete by `(season_end_year,
tier)`. Both must become `AND division_id = ?`. Without this, ingesting NL
South silently deletes the NL North rows just written, with no error.

---

## `level.OUTSIDE` — the delicate one

`src/level.py:42` sets `OUTSIDE = 6`, the sentinel for "season in a club's
window with no standings row". A real tier 6 collides with it.

**`OUTSIDE = 99`.** Not `None` (already means "insufficient record"), not a
separate flag (churns the dataclass, the JSON schema and every consumer).
A large int keeps `median_low` ordering correct — "outside" must sort below
every real tier.

**Two functions break arithmetically, and both are silent.** Verified:

- **`_spread()` (`level.py:148-158`)** returns `max(repeated) -
  min(repeated) + 1`. A club repeatedly in tier 1 and repeatedly outside
  currently gives 6; with 99 it gives **99**, which always clears the
  `_spread(buckets) >= 4` test in `classify()` (`level.py:213`) and
  relabels a large number of clubs "broad" / "whole-pyramid range". Fix:
  compute the span over non-`OUTSIDE` buckets, adding 1 if `OUTSIDE` is
  itself repeated.
- **`_adjacent()` (`level.py:161-172`)** probes `primary ± 1`. Tier 5 and
  outside are adjacent today *only by accident of the sentinel being 6* —
  which is what makes "National League / non-league yo-yo" work. Fix:
  an explicit `BUCKET_LADDER = [1, 2, 3, 4, 5, 6, OUTSIDE]` with
  index-based adjacency. That is what the code always meant.

Also flag, don't silently change: with six real tiers, `_spread >= 4` for
"whole-pyramid range" is arguably `>= 5` now.

Straight symbol swaps: `level.py:90, 179, 199, 270, 290`, `digest.py:226`.
`TIER_NAMES[6]` should be `"National League North & South"` — a single
name, with per-division naming living in `divisions.py`.
`site_build._natural_level:1010` hardcodes `["1","2","3","4","5","outside"]`
and must be built from `TIER_NAMES`, or the tier-6 bucket is dropped from
the distribution bar while still counting in the denominator.

### The one ordering constraint that cannot be relaxed

The sentinel **is** persisted. Verified against the live DB:

```
club_trajectory.natural_level_tier        = 6 →  3 rows
club_trajectory.recent_level_tier         = 6 →  5 rows
club_trajectory.natural_level_second_tier = 6 →  2 rows
```

`trajectory.rebuild_trajectory()` drops and rebuilds the table every run,
so there is nothing to migrate — **provided the sentinel change and the
rebuild both happen while zero tier-6 standings rows exist.** Do it in the
other order and a persisted `6` is ambiguous between "outside" and "tier
6", and no repair script can tell them apart. This is the hard gate between
Phase 1 and Phase 4.

---

## Charts: max-band, not sum-band

`charts.overall_positions` (`:92-99`) gives NLN 1st and NLS 1st the same
overall position. That is **correct** — they are at the same level. The
actual defect is `charts.tier_floors` (`:43-75`), which does `GROUP BY
tier`, reads 48 for tier 6, and over-extends the y-axis by a phantom
division so the chart's bottom quarter is permanently empty.

Make a tier's band width the **max division size**, not the sum:

```sql
SELECT tier, MAX(n) FROM (
    SELECT tier, division_id, COUNT(*) AS n
    FROM standings WHERE season_end_year = ?
    GROUP BY tier, division_id
) GROUP BY tier ORDER BY tier
```

For every 1-division tier `MAX == COUNT`, so **tiers 1–5 produce identical
floors and `max_pos`** — which is exactly what makes this refactor
verifiable as a no-op.

While there, kill a duplication: the offset subquery is copy-pasted between
`charts.py:92-99` and `site_build.py:2294-2299`. Extract
`charts.band_widths(conn)` and `charts.tier_offsets(conn)` returning
`{year: {tier: ...}}`, and add the offset in Python (both callers already
return Python lists). `static/chart.js` needs no change — it consumes
`tierFloors` and `maxPos`.

Rejected: sum-band (says NLS 1st finished 24 places below NLN 1st — false);
proportional remap (fractional positions, breaks "position 1 is a row");
per-tier independent scales (destroys the continuous-axis premise).

---

## Curated ingest

**One file, `curated_standings.csv` at project root**, matching the
existing convention (`club_master.csv`, `club_finances.csv`,
`points_deductions.csv`). The tier-5 backfill rows go in it too —
`division_id` distinguishes them, and there is one loader to test. ~1,740
rows ≈ 200 KB.

```
season_end_year, division_id, position, club_name, club_id,
played, won, drawn, lost, gf, ga, gd, points,
status_override, source, note
```

- `club_name` resolves through `entities.resolve_name`, so `name_variants`
  stays the single home of club-naming knowledge. `club_id` is optional and
  **authoritative when supplied** — the escape hatch for genuinely
  ambiguous non-league names (Hyde/Hyde United, the Chester and Bradford
  Park Avenue lineage breaks). Log loudly when it disagrees with the
  resolver.
- `status_override` normally blank. Do **not** hand-write 1,740 statuses:
  let `status.assign_status()` derive from position, then let
  `pipeline._reconcile_statuses()` correct from next-season movement, which
  for full-history curated data is complete evidence. Reserve the override
  for expunged records, mid-season resignations, lateral NLN↔NLS transfers
  and ground-grading refusals.
- `source` required-ish; blank inherits from the first populated row for
  that `(season, division_id)`. This site prints provenance everywhere.

**`src/curated.py`**, shaped like `deductions.seed_points_deductions`.
Called from `pipeline.run()` after the file loop, before
`_mark_data_completeness()`. Unconditional, like the other seeds — the
weekly workflow's `--season-start CUR` filters *files*, not seeds.

Validation, all fatal: `played == w+d+l`; `points == w*3+d`; `gd == gf-ga`;
positions `1..n` with no gaps or dupes; row count matches
`status.get_rules(division_id, year)["total_clubs"]`; **`division_id` not
already ingested by the match path this run** (stops a curated tier-5
backfill clobbering real 2006+ rows); and **an unresolved `club_name` is
fatal**. That last one matters most: `pipeline.py:233-236` currently
inserts `club_id = NULL`, prints a report and **exits 0** — defensible for
a third-party feed, indefensible for hand-written data where an unresolved
name is a typo.

Writes `DELETE ... WHERE season_end_year = ? AND division_id = ?` for
exactly the keys in the CSV, then inserts, with `source = 'curated/…'` so
`WHERE source LIKE 'curated%'` is a clean predicate downstream.

### `data_complete` for a matchless tier

Correcting a hazard I flagged earlier: `_coverage_note`
(`site_build.py:495-521`) does **not** currently misfire on tier 6 — it
returns early on `COALESCE(data_complete, 1)`, and
`_mark_data_completeness` skips divisions with zero matches. Verified. The
`n_teams * (n_teams - 1)` line is a latent hazard, not a live bug.

Treatment: curated rows get `data_complete = 1` **explicitly** — the
loader's arithmetic checks are stronger evidence of a settled final table
than a match count is, and this makes tier-6 rows legitimately eligible for
the records tables, which filter on `COALESCE(s.data_complete, 1) = 1`
(`site_build.py:2705-2707`). Then add a *distinct* note rather than reusing
the incomplete-data one:

> Final table only. This division's match-by-match results are not in the
> source data, so head-to-head records and form guides are unavailable.

Also replace the duplicated `expected = n_teams * (n_teams - 1)` with
`aggregate.expected_match_count(n_teams)`.

---

## Status rules

Re-key `status.RULES` from `(tier, from, to)` to `(division_id, from, to)`
— a mechanical rename of 25 keys, and the change that removes "tier is the
division key" from its last home. Same for `CURRENT_SEASON_PLAYOFF_WINNERS`
(`status.py:33-38`), which then holds `("national-league-north", 2026)` and
`("national-league-south", 2026)` as two ordinary entries. Callers:
`assign_status`, `pipeline._club_count_plausible:162-185`,
`_apply_points_deductions`, `_apply_known_playoff_winners`.

Fix two silent-disable bugs while there: `_club_count_plausible` returns
`True` on `KeyError` with no log line, and `assign_status`'s `KeyError`
path marks **every club "Stayed"** behind one easily-missed warning.

- **Era 2 (2005/06–)**: genuinely rule-shaped. 22 clubs then 24, champion
  up, play-offs, bottom N down. 2020/21 tier 6 was **voided** — the CSV
  should simply have no rows, and the site shows the gap, which is true.
- **Era 1 (1993/94–2003/04)**: do **not** encode promotion positionally.
  Three leagues shared a promotion slot decided partly off the pitch. Set
  `auto_promote = ()` and `playoff_promote = ()`, set `total_clubs` and the
  real `auto_relegate` band, and let `_reconcile_statuses()` derive
  promotion from next-season movement. A champion who went up gets
  "Champions" from `pos == 1`; a champion who didn't *also* gets
  "Champions", and `_reconcile_statuses` never rewrites it — which is both
  correct and honest. Spot-check Stevenage 1996 and Macclesfield 1995.

---

## The curation burden

| Stage | Scope | Seasons | Rows | New clubs |
|---|---|---|---|---|
| **4A** | NLN + NLS, 2005/06– | 22 | ~1,010 | ~100–120 |
| **4B** | Tier-5 backfill, 1993/94–2004/05 | 12 | ~264 | ~10–20 |
| **4C** | NPL / Isthmian / Southern, 1993/94–2003/04 | 11 | ~726 | ~70–90 |
| | | | **~2,000** | **~200–230** |

Calibration from your own data: tier 4 (closed, 24 clubs) produced 80
distinct clubs in 34 seasons; tier 5 (open, 24 clubs) produced **97 in 22
seasons** — about four new clubs a year, and churn accelerates downward.
`club_master.csv` goes from 164 rows to ~380, a 2.2× expansion. All 164
existing rows carry `name_variants`, colours, stadium and coordinates.

Four things make this tractable:

1. **Stage 4A first.** It is hole-free on its own and needs no tier-5
   backfill.
2. **4B is the cheapest and highest-return stage.** 264 rows and ~15 clubs,
   and it lets you *delete* code: `level.TIER5_FIRST_SEASON`, the whole
   `coverage_note == "pre2006-gap"` mechanism, `OUTSIDE_NAME_AMBIGUOUS`,
   `team.html:34`'s "tier 5 only from 2005/06" caveat, and the hedging
   inside `_hook_fell_out_of_the_league`.
3. **Degrade `club_master` fields by stage.** Colours and coordinates are
   optional — `site_build.color()` falls back to `DEFAULT_COLOR` and
   `build_map` joins on `latitude IS NOT NULL`. New clubs can land with
   id/name/variants only. **Don't let ground research block the data.**
4. **Mint slugs programmatically.** `club_id` is permanent; a typo in one
   of 200 hand-written slugs is forever. Write `slugify(canonical_name)`,
   generate every new id with it, and test `slugify(canonical_name) ==
   club_id` for all rows with an allowlist for existing exceptions
   (`guiseley-afc`, `dagenham-and-redbridge-fc`).

### Two `entities.py` landmines to defuse *before* bulk edits

- `seed_club_master` **deletes DB rows absent from the CSV and NULLs their
  `standings.club_id`** (`entities.py:73-92`). On a 400-row CSV a botched
  merge silently detaches history. Abort if `len(stale) > 5` unless an
  explicit `--allow-club-removals` flag is passed.
- `_add_variant` resolves collisions by keeping the alphabetically-first
  `club_id` and logging at `error` (`entities.py:172-186`). With 200 new
  non-league clubs, collisions are near-certain (Bedford Town/Bedford,
  Ashford Town ×2 — Kent and Middlesex). Add a test that `build_resolver`
  produces zero collisions, so it fails CI rather than scrolling past.

---

## Phased sequence

**Phase 0 — registry + column. Provably a no-op.**
`src/divisions.py`; re-point the four hardcoded tables; add `division_id`
to both tables via `_migrate_standings_columns`; backfill from tier; create
the unique index.
*Gate:* 268 tests pass unchanged; `COUNT(*) WHERE division_id IS NULL` = 0;
rebuilt `site/` byte-identical.

**Phase 1 — the sentinel. The irreversible one.**
`OUTSIDE = 99`; rewrite `_spread` and `_adjacent` (ladder-based);
`TIER_NAMES[6]`; `_natural_level`'s key list; `digest.py:226`. Run the
pipeline, commit the regenerated `england.db`.
*Gate, hard:* `COUNT(*) FROM club_trajectory WHERE natural_level_tier = 6
OR recent_level_tier = 6 OR natural_level_second_tier = 6` must be **0**,
and no tier-6 standings row may exist yet. Diff `site/` against Phase 0 and
confirm every `natural_level_label` is unchanged — eyeball Altrincham,
Stockport, Wrexham.

**Phase 2 — N-division plumbing. Still zero tier-6 rows.**
Re-key `RULES` and `CURRENT_SEASON_PLAYOFF_WINNERS`. Scope by `division_id`
in `pipeline._process_season` (both DELETEs), `_mark_data_completeness`,
`_apply_points_deductions`, `_apply_known_playoff_winners`,
`_club_count_plausible`; and in `site_build.season_divisions:468-493`,
`build_divisions:948-985`, `build_matrix:1353-1363`, `_coverage_note`,
`_finance_ranks:2014`. Fix `_season_progress_note:625-645` — `total` must
count divisions active that year, not `len(TIER_SLUGS)`, and `started`
must count divisions too, or the note sticks permanently. `tier_floors` →
max-band; extract `band_widths`/`tier_offsets`; delete the duplicated SQL.
Fix the bare `TIER_SLUGS[tier]` subscript at `site_build.py:484`.
*Gate:* built site **byte-identical** to Phase 1 — achievable because every
tier is still 1-division and max == sum. Make this an acceptance criterion.

**Phase 3 — tier-6 presentation, driven by a synthetic fixture.**
Extend `test_digest._make_db` with a two-division tier so all of this is
testable before any curation exists.
`--tier-6` in `static/style.css:14-19` (suggest `#8d6e63`, extending the
ramp into brown, clearly distinct from `--tier-out: #9aa3ab`), plus
`.nl-tier-6:446-450` and `.ribbon-cell.t6:548-552`; rewrite the `:38-43`
comment reserving 6 for "outside". **Add a test asserting every tier in
`TIER_NAMES` has a `--tier-N` var and both class rules** — four hand-synced
colour locations is exactly the drift a five-line test kills. `map.js:19-22`
gains 6 (its legend builds itself from that dict). Render
`templates/map.html:19-24`'s five hand-written chips from a context var.
Add a literal `fill=` alongside `style="fill: var(--tier-N)"` in
`insight_scatter.html:69` so a missing var can't produce an invisible dot.
`_ribbon:1740-1757`, `teams_index` others-bucket label `:1189-1195`,
`_insight_safe_thresholds:2783-2846` (derive the note from the division
list — NLN/NLS are 46-game and will join that table; era-1 22-club seasons
are 42-game and correctly excluded), `_hook_fell_out_of_the_league:684-753`
(`s.tier = 5` → `>= 5`; the answer doesn't change today but the statement
becomes precise). Keep `_disclosure_counts:2230`'s `tier <= 5` — finance
data genuinely only exists for tiers 1–5 — and fix the copy instead. Then
the ~30 copy strings (`base.html:34`, `home.html:4,56`, `chart.html:4`,
`matrix.html:8`, `map.html:4`, `team.html:34`, `matrix.js:20,36`,
`map.js:48,115`, `digest.py:433`, `README.md`) and
`tests/test_site_build.py:736`'s `range(1, 6)`.

**Phase 4 — data. Three independent PRs: 4A → 4B → 4C.**
Each with its own `club_master.csv` additions, each independently
deployable and revertible, because a stage's rows are identified by
`division_id` and delete cleanly.

### Where the irreversible risk is

1. **Phase 1 before Phase 4.** Out of order, `natural_level_tier = 6`
   becomes ambiguous and unrecoverable.
2. **The committed `england.db`.** Every phase touching derived columns
   needs a regenerate-and-commit, and the weekly workflow pushes its own DB
   update — a stale `england.db` in `main` plus a schema change in a PR is
   a binary merge conflict. Land these on short-lived branches.
3. **200 permanent slugs minted at once.** Mitigated by slugify + test.
4. **`seed_club_master`'s silent delete-and-NULL.** Guard it *before*
   Phase 4 starts.

## Verification

- `python3 -m pytest tests/ -q` at every phase — 268 passing now.
- **Phases 0 and 2 must produce a byte-identical `site/`.** Build, hash
  every file, diff against the previous phase. This is the strongest
  available proof the refactors preserved behaviour, and it works precisely
  because tiers 1–5 are 1-division tiers.
- `python3 src/site_build.py` — 245 pages now; expect +2 division pages per
  tier-6 era after Phase 4.
- Internal link check (14,840 links, zero broken) after every phase.
- After Phase 1: the persisted-sentinel query returns 0, and
  `natural_level_label` is unchanged for every club.
- After Phase 4A: spot-check a club that moved NLN↔NLS (a lateral move must
  read as neither promotion nor relegation), and confirm the home page's
  `_hook_fell_out_of_the_league` still names Oldham — the recipe
  self-retires to a count if a second club qualifies, so this is a live
  check of whether new data changed the answer.
- After Phase 4C: spot-check Stevenage 1996 and Macclesfield 1995, the two
  cases where a champion did not go up.

## Delivery

Branch per phase from the current tip of `origin/main` (`43adc58`). Per
`CLAUDE.md`, open a PR and merge automatically once tests and the build
pass — except Phase 1 and each Phase 4 data stage, which change the
committed database and are worth a look before merging.
