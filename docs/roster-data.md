# The tier-6/7 roster — how it was built

`src/roster.py` reads **`club_roster.csv`** and `catchment._club_frame` unions
it with `club_master`, so the gravity model can see clubs that have never
played in the top five tiers. The model now works over **245 clubs**, up from
165.

## Why it exists

This site records tiers 1–5, but the catchment model is a model of
**competition**, and competition does not stop at the fifth tier. Without the
roster the model could not see a club that had never been in the top five, so
it credited that club's neighbours with a town that is not free — the same
defect as `current_tier = 0`, and larger, because more clubs were missing than
were ever mislabelled.

## The source

**The FA's National League System club allocations for 2026/27, steps 1–4.**
The governing body's own list, settling every club at tiers 5 to 8 in one
document.

```
https://www.thefa.com/-/media/thefacom-new/files/competitions/2026-27/nls/nls-1-to-4-club-allocations-2026-27---v1-140526.ashx
```

`www.thefa.com` is refused at this environment's network proxy, as are
Wikipedia and every league and club site tried, so the PDF was supplied by
hand. **Web search was tried first and was not good enough**: reconstructing
the National League North line-up from search snippets produced 24 clubs of
which two were not in the division (Scunthorpe United, whom this repo's own
database puts in the fifth tier, and Alfreton Town) while two that are were
missing (Chorley, Southport).

### Extracting it

`scripts/parse_nls_allocations.py` writes
**`data/raw/nls-allocations-2026-27.tsv`**. There is no PDF tooling installed
here — no `pdftotext`, no `pypdf`, no poppler — and none is needed: the pages
are Flate-compressed streams of ordinary text operators that `zlib` and `re`
read directly.

The parse is geometric, so it needs a check that is not. Two of them:

- **Every division must come out its real size** — 24/24/22/22/22/22. The
  first run failed this, and the failure was real: a row's rank number and
  its name are often drawn in *different* content streams, so keying rows by
  stream lost Carlisle United, Hornchurch and Three Bridges outright.
- **The step 1 column must equal this repo's own fifth tier.** The FA's list
  and the site's in-progress 2026/27 standings are unrelated sources for the
  same 24 clubs, and they agree exactly, every name resolving through
  `entities.build_resolver`. That validates the column geometry, the fragment
  joining and the name matching in one shot.

Both are `tests/test_roster.py` tests, not just script assertions.

## What it produced

| | |
|---|---|
| Clubs in the allocations at tiers 6 and 7 | 136 |
| Already in `club_master` | 40 |
| Successors folded into an existing id | 5 |
| **Placed in `club_roster.csv`** | **71** (18 at tier 6, 53 at tier 7) |
| Unplaceable, reported not guessed | 20 |

### Successors, not new clubs

Five clubs the FA names are the successors of companies this site already
holds an id for, in the same town — so they get a **name variant and a
corrected tier on the existing row**, not a roster row. A roster row would
have been the same club twice, competing with itself for its own town. This
is the rule already applied to Chester, Bury and Hereford.

| The FA's name | Folded into | Tier |
|---|---|---|
| Scarborough Athletic | `scarborough-fc` | 6 |
| Merthyr Town | `merthyr-tydfil-fc` | 6 |
| Enfield Town | `enfield-fc` | 7 |
| Bromsgrove Sporting | `bromsgrove-rovers-fc` | 7 |
| Leamington | `ap-leamington-fc` | 7 |

### Seventeen more tier corrections

The allocations settle every label the previous commit had to leave open.
Six clubs were recorded as `0` — exerting no pull, their towns handed to
neighbours — while playing in the sixth or seventh tier: **Farnborough,
Hednesford Town and Slough Town** at 6, **Leek Town, Redditch United and
Worcester City** at 7. Seven more were a tier too high: Dartford, Guiseley,
Havant & Waterlooville, Kettering Town, Lewes, St Albans City and Welling
United, all at 7 rather than 6. With the four successors above, seventeen
rows of `club_master.csv` changed tier.

## Coordinates: how a club is placed, and how wrong that is

Ground coordinates for non-league clubs are not reachable from here either, so
`scripts/place_clubs.py` places a club at the population-weighted centroid of
its **local authority**, computed from `msoa_demographics.csv`.

That is a guess, so it is published with its measured error. `place_clubs.py
validate` places the clubs that **do** have a surveyed ground by the same
method:

| Authority spread | n | median | p90 | max |
|---|---|---|---|---|
| 0–4 mi | 86 | 1.4 | 2.8 | 3.7 |
| 4–6 mi | 32 | 2.0 | 2.9 | 4.4 |
| 6–9 mi | 21 | 2.3 | 5.3 | 8.0 |
| **9+ mi** | 22 | **8.9** | **16.8** | **35.7** |

The cliff is at nine miles, which is where `MAX_SPREAD_MILES` sits. Past it
every case is a large rural authority — Cornwall, Somerset, Cumberland, North
Yorkshire — whose centroid stands in for no town at all. Below it the worst
case is Guiseley at 8.0 miles: a club at the edge of a big city's authority,
which is the failure mode that remains.

**The threshold is a trade between two errors, not a safety margin.** A club
the model cannot see has its town handed to its neighbours, which is the bug
this whole layer exists to fix, so excluding a club is not the cautious
option it looks like. At six miles, 39 of 91 clubs were refused; at nine, 20
are.

Clubs outside England cannot be placed at all — the gazetteer is English
MSOAs. They are easy to identify and are excluded from the validation too:
every English ground is within 1.5 miles of an MSOA centroid, while the Welsh
ones are 8.8 to 30.8.

### Precision is recorded, never inferred

`club_roster.location_precision` is `ground` or `town`, and `club_master.csv`
now carries the same column — `ground` for its 165 surveyed grounds, `town`
for the nine placed by centroid. `src/prospects.py` reads it and prints an
approximate rival distance as `~7mi`, because Bury and Radcliffe share an
authority centroid and are three miles apart in fact; printing `0mi` would be
a precision the data does not have.

### The twenty that are still invisible

Four at tier 6 — **AFC Totton, Chesham United, Spalding United, Spennymoor
Town** — and sixteen at tier 7: Banbury United, Bury Town, Chichester City,
Chippenham Town, Evesham United, Frome Town, Gainsborough Trinity, Hitchin
Town, Leighton Town, Leiston, Malvern Town, Stamford, Stratford Town, Taunton
Town, Whitby Town, Wimborne Town. Each sits in an authority too wide to stand
in for its town. A town-level gazetteer would close all twenty at once; the
count is pinned in `tests/test_roster.py` so it cannot grow unnoticed.

## What it changed

**Every one of the 165 clubs already in the model lost catchment**, which is
the expected direction: population that had been credited to them is now
claimed by neighbours the model could not previously see.

The contest ratio mostly *fell*, and that is worth understanding rather than
celebrating. `contest_ratio` asks what share of its own Voronoi cell a club
keeps. Adding clubs shrinks every cell to a tighter, more local area, and a
club keeps more of a smaller cell. So the measure has become stricter about
what counts as a club's own ground, and the numbers before and after are not
directly comparable.

| Club | catchment | contested |
|---|---|---|
| Maidstone United | 217,868 → 205,634 | 75% → **56%** |
| Morecambe | 162,718 → 148,230 | 52% → 33% |
| Southport | 160,710 → 156,797 | 51% → 35% |
| Macclesfield Town | 171,551 → 166,429 | 60% → 49% |
| Bury | 499,017 → 481,230 | 48% → 34% |
| Hereford United | 336,902 → 316,419 | 43% → 36% |

**The conclusion held, on a thinner margin.** Maidstone is still the most
contested of the four buyable-or-maybe clubs, but its lead narrowed from 15
points to 7: it fell 19 points, as did Morecambe, against Southport's 16 and
Macclesfield's 11. Its nearest rival is now Tonbridge Angels rather than
Gillingham — a club the model could not see at all until today.

## Rebuilding it

```bash
python3 scripts/parse_nls_allocations.py ALLOCATIONS.pdf
python3 scripts/place_clubs.py validate          # the error table above
python3 scripts/place_clubs.py authorities 9     # which authorities qualify
python3 scripts/place_clubs.py place clubs.tsv > club_roster.csv
```

The `place` input is one club per line, tab separated. The local authority is
the only field that cannot be derived from the allocations document:

```
canonical_name <TAB> local_authority <TAB> tier <TAB> division <TAB> ground_name
```

`seed_club_roster` refuses a row rather than warning when it would mislead:

| Rejection | Why |
|---|---|
| `club_id` already in `club_master` | The club would compete with itself and each copy would take about half its real share |
| `tier` with no entry in `TIER_ATTRACTIVENESS` | It would silently fall through to the default weight and pull like a step-3 club |
| coordinate outside England's bounding box | A transcription error, not a place |
| `club_id` that does not start with `slugify(canonical_name)` | A typo in a hand-written id is permanent and invisible |
| `location_precision` not `ground` or `town` | The reader is entitled to know which they are looking at |

## What the roster does not do

It adds **competitors, not candidates**. A club with no `standings` rows
cannot have a Football League ceiling, so `prospects.candidates()` never
returns one. Nothing in this layer changes who is for sale.
