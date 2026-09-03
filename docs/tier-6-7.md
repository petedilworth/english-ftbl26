# Tiers 6 and 7 — where the data came from and what it cost

The site records the sixth and seventh tiers for **2012/13 to the season being
played**, 1,712 club-seasons. It comes from two sources with a hard join
between them, and this is how.

| seasons | source | dates? |
|---|---|---|
| 2012/13 – 2018/19 | `jalapic/engsoccerdata`, match-level | yes |
| 2019/20 – present | Wikipedia results grids | **no** |

## The source

`jalapic/engsoccerdata`, the same project this repo already uses for the
pre-1994 backfill and for tier 5 — `src/historical.py` reads all three from
one base URL. The non-league file is `data-raw/england_nonleague.csv`: 57,394
rows, **match-level**, in the same column shape as the others.

Match-level is the point. `aggregate.compute_standings` derives every table
from results using the site's own points rule and era tiebreak, exactly as it
does for tiers 1–5, so no table here is transcribed from a published one.

**Everything else was blocked.** `thefa.com`, Wikipedia, the National League's
own site, footballwebpages, thefishy, 11v11, fchd.info, RSSSF and the Internet
Archive are all refused at this environment's network proxy, and the GitHub
API is bound to this repository. `raw.githubusercontent.com` is the one open
door, which is why a dataset already trusted here was worth more than a better
one that could not be reached.

## The seven seasons

| Division | Seasons | Clubs |
|---|---|---|
| National League North | 2012/13 – 2018/19 | 22 |
| National League South | 2012/13 – 2018/19 | 21–22 |
| Isthmian League Premier | 2012/13 – 2018/19 | 22–24 |
| Northern Premier League Premier | 2012/13 – 2018/19 | 22–24 |
| Southern League Premier | 2012/13 – 2017/18 | 22–24 |
| Southern League Premier Central / South | 2018/19 | 22 each |

The Southern League Premier was **one division until 2017/18 and two after**,
so `divisions.Division` carries `first_season` / `last_season` and all three
ids are real. The single division is not a predecessor of either half; it is
the thing that was split, and its six seasons belong under its own name.

## Nineteen matches that are not league matches

A completed league season is a round-robin: each ordered pair of clubs meets
once at each ground. Nineteen pairs meet twice, and `historical.
_drop_repeat_fixtures` separates two quite different reasons, because they are
not the same problem.

**Play-offs — seventeen matches, dropped.** Kidderminster v Chorley and
Salford City v FC Halifax Town in the 2016/17 National League North, played on
3, 7 and 13 May: the semi-finals and the final. Counting them would award
points that were never league points and move clubs up the table. The window
is 20 April to 31 May, compared as month-day — a December date is "after
April" on a numeric reading, and one of them is.

The date decides before the score does, and that ordering matters: **FC
Halifax Town beat Chorley 2–1 in the play-off final having also beaten them
2–1 in January**, so a same-score test alone would call a play-off a double
entry.

**Conflicts — three, reported as warnings.** Dulwich Hamlet v East Thurrock
United appears on consecutive days in August 2018 with the same 2–1 score,
which is plainly one match entered twice. Truro City v Concord Rangers and
Swindon Supermarine v Basingstoke Town each appear twice with *different*
scores, months apart, and this source cannot say which counted. The earlier is
kept, and that is a choice rather than a fact, so it is logged as one.

One table is short: **2018/19 Northern Premier League Premier has 453 of 462
matches**, so it is part-played and the site says so.

## What it cost

**158 clubs joined `club_master`** — 118 that appear in these seasons and 40
more that the FA's 2026/27 allocations name but this data does not reach. `club_roster.csv` and `src/roster.py`
are retired: they existed only because a club with no league history had
nowhere to keep an identity, and now every one of them has standings rows.

The audit that made the fold safe: **no tier-1-to-5 standings row changed.**
Adding 158 names to the entity resolver could have re-resolved an existing
spelling; it re-resolved none, and the test pins it.

**The `level.py` ladder is seven tiers deep now**, and two consequences are
worth stating rather than discovering:

- **"Whole-pyramid range" is two thirds of the rungs**, which was 4 of 6 and
  is now 6 of 8. Eighteen clubs lost the label — Luton, Wimbledon, Wrexham,
  Bolton and others whose range is tiers 1 to 5. That range is wide and it is
  no longer the whole of a seven-tier pyramid, so the label going is correct.
- **Four clubs lost a true label to the coverage gap.** Boston United, Dover
  Athletic, Tamworth and Welling United all bounce between the fifth tier and
  below it, and their below-the-line seasons are now split in two — tier 6
  where the data reaches, "outside" where it does not — so neither bucket is
  large enough to earn the "National League / non-league yo-yo" they plainly
  deserve. Extending the coverage closes this; nothing in `level.py` can.

Five clubs gained one for the opposite reason: Alfreton Town, Brackley Town,
Canvey Island, Lewes and Oxford City are now visibly yo-yoing across a
boundary the site could not previously see.

## What is still missing

**Nothing before 2012/13.** The seven-season hole *after* 2018/19 is closed;
see "The second source" below.

**Tier 7 has no 2019/20 or 2020/21, and never will.** The FA declared steps 3
to 6 null and void in March 2020 and expunged them again in February 2021.
Those seasons were not played to a finish and have no table to record. That is
absent structure, not missing data, and the coverage test encodes it.

**Twenty of the new clubs have no coordinates**, because their local authority
is too wide to stand in for a town — see `scripts/place_clubs.py`, which
publishes its own measured error. They appear in the tables and on the ladder
and not on the map or in the catchment model, which is the honest treatment
for a club whose location this project cannot fix.

**Sixty-seven have no `current_tier`.** They played at the sixth or seventh
tier in these seasons and this project does not record where they are now.

It was eighty-two. The FA allocations
(`data/nls-allocations-2026-27.tsv`, kept out of `data/raw/` because that
directory is gitignored and this file cannot be fetched again) settle steps 1
to 4, and this file was in the repo read by nothing but its own tests. Checked
against `club_master.csv` it disagreed about **nobody** and answered
**fifteen** blanks - fewer than the twenty estimated here before anyone
counted. Those fifteen are filled, and a test now holds the two files in
agreement: a disagreement is a wrong answer on the page, a blank the FA has
already answered is a lazy one.

The remaining sixty-seven play below step 4, where the FA list stops. Blank
means unknown, and the catchment model gives an unknown club no pull rather
than a guessed one.

## The second source: Wikipedia results grids

engsoccerdata stopped updating its non-league sets, and nothing below the fifth
tier exists on any host this environment can reach — `openfootball/england`,
its mirror `footballcsv/england`, `worldfootballR_data` and
`jfjelstul/englishfootball` all stop at tier 5, and `en.wikipedia.org` is
refused at the proxy by both `curl` and `WebFetch`. **That is settled and
should not be re-checked.**

So 26 season articles were fetched as raw wikitext on a machine that can reach
them, and `scripts/parse_wiki_results.py` extracts the results grids:

```
|team_order=ALF, BAN, BIS, ...
|name_ALF= [[Alfreton Town F.C.|Alfreton Town]]
|match_ALF_BAN=2-0 |match_ALF_BIS=3-0 ...
```

The key names the home club and then the away one, so no fixture is inferred.
**15,847 matches across 40 division-seasons**, and every table is still
computed from results by this site's own points rule — the property that makes
these seasons the same kind of thing as tiers 1 to 5 rather than a
transcription. The derived CSVs live in `data/nonleague/`, not `data/raw/`,
which is gitignored on the premise that everything in it can be fetched again.
These cannot.

**What the grids do not carry is dates.** `match_date` is nullable throughout,
so these seasons have no date-derived features.

### Two things the grids get right that a league table would not

**Expunged clubs.** Marske United resigned from the Northern Premier League in
January 2024 and their record (P22 W7 D0 L15) was struck out, so 2023/24 was
completed by 21 clubs under a 22-row table. The grid lists 21 and is correct;
reading the club list from the table instead would have marked three complete
seasons as short.

**Awarded matches.** Two 2023/24 National League South cells hold `H/W` rather
than a score — Slough Town v Bath City, abandoned for a medical emergency in
the crowd and awarded, and Weymouth v Yeovil Town. Points come from `FTR` and
goals from `FTHG`/`FTAG` separately, so these carry the right result with a
nominal 1–0: the table is exact, the goal difference understated by one match.

## The prediction this document made, and got wrong

An earlier version of this page said four clubs — Boston United, Dover
Athletic, Tamworth and Welling United — lost a "National League / non-league
yo-yo" label purely to the coverage gap, and that extending the data would give
it back. **It did not.** The seasons moved out of "outside" and into tiers 6
and 7 exactly as intended, and all four now run to the season being played
rather than stopping in 2019, but only Welling United's label changed at all —
to "National League North & South club".

The diagnosis was too simple. A yo-yo label needs the top two adjacent levels
to hold three quarters of a club's seasons, and these clubs are spread wider
than two. Boston United went from 54% across their best pair to 65% and are
still short, because five of their seasons are at the fourth tier and twelve
are **below the seventh** — a level this site still does not record. No amount
of tier-6/7 coverage consolidates a record that reaches past both ends of it.

"Mixed" is the honest description, and it is what they carry.
