# The tier-6/7 roster — what is built, and the one thing it needs

`src/roster.py` reads **`club_roster.csv`** at the repo root and
`catchment._club_frame` unions it with `club_master`. **The file does not
exist yet**, and the code degrades the way the catchment loader does: the
seed logs and returns 0, the union finds no roster table, and the model goes
back to seeing only clubs with league history.

## Why the roster is needed at all

This site records tiers 1–5, but the catchment model is a model of
**competition**, and competition does not stop at the fifth tier. Until the
roster exists the model cannot see a club that has never been in the top
five, so it credits that club's neighbours with a town that is not free.

The distortion falls hardest exactly where the screen looks. A club that has
fallen to the sixth tier is surrounded by sixth- and seventh-tier neighbours,
none of them in the model, so its catchment is flattered and its contest
ratio understated. This is the same defect class as the `current_tier = 0`
bug fixed in the previous commit — a club the model cannot see is a town
given away — and it is larger, because there are more clubs missing than
there were clubs mislabelled.

## What is needed: one file

**The FA's National League System club allocations for 2026/27, steps 1–4.**
It is the governing body's own list, published each May, and it settles every
club at tiers 5, 6, 7 and 8 in one document:

```
https://www.thefa.com/-/media/thefacom-new/files/competitions/2026-27/nls/nls-1-to-4-club-allocations-2026-27---v1-140526.ashx
```

`www.thefa.com` is refused at the network proxy in this environment, as are
`en.wikipedia.org` and every league and club site tried. Web *search* works
and returns summaries; it is not good enough for this job, and the attempt
proved it. Reconstructing the National League North line-up from search
snippets produced a list of 24 that contained two clubs which are not in the
division (Scunthorpe United, who are in the fifth tier — the repo's own
database says so — and Alfreton Town, allocated to the Northern Premier
League) and omitted two that are (Chorley and Southport). A roster with two
clubs in the wrong division puts two towns' populations in the wrong place,
silently, and there is no downstream check that would catch it.

The National League South line-up **was** recoverable, and it cross-checks
cleanly against this repo's own data: search gives 24 clubs including
Braintree Town and Truro City, and `standings` independently records both as
relegated from tier 5 in 2026. That is the standard the North list has to
meet and cannot, from here.

**A partial roster is worse than none.** Seeding the South alone would leave
northern candidates — Morecambe, Southport, Macclesfield, Chester, Darlington
— competing against an empty map while Maidstone competes against a full one,
and the screen would report the difference as a fact about the clubs. So
nothing is seeded until both halves can be.

## The columns the loader expects

Required: `club_id`, `canonical_name`, `tier`, `latitude`, `longitude`,
`location_precision`. Optional: `division`, `ground_name`, `locality`,
`source_url`, `notes`.

`seed_club_roster` refuses a row rather than warning when it would mislead:

| Rejection | Why |
|---|---|
| `club_id` already in `club_master` | The club would compete with itself and each copy would take about half its real share |
| `tier` with no entry in `TIER_ATTRACTIVENESS` | It would silently fall through to the default weight and pull like a step-3 club |
| coordinate outside England's bounding box | A transcription error, not a place |
| `club_id` that does not start with `slugify(canonical_name)` | A typo in a hand-written id is permanent and invisible |
| `location_precision` not `ground` or `town` | The reader is entitled to know which they are looking at |

## Coordinates: how a club is placed, and how wrong that is

Ground coordinates for non-league clubs are not reachable from here either,
so `scripts/place_clubs.py` places a club at the population-weighted centroid
of its local authority, computed from `msoa_demographics.csv`, and the row
records `location_precision = town`.

That is a guess, so it is published with its measured error.
`place_clubs.py validate` places the 165 clubs that **do** have a surveyed
ground by the same method and compares:

| Set | n | median | p90 | max |
|---|---|---|---|---|
| all clubs with a ground | 165 | 1.8 mi | 8.0 | 38.5 |
| authority spread ≤ 6 mi | 118 | **1.5 mi** | **3.0** | **4.4** |
| authority spread > 6 mi | 47 | 4.4 mi | 16.2 | 38.5 |

The whole tail is large rural authorities — Cumberland, North Yorkshire,
Wiltshire — where the centroid is near no particular town. So the threshold
is on the authority, not on the club: an authority whose population spreads
more than `MAX_SPREAD_MILES` cannot place anybody, and the club is reported
unplaced rather than put in the wrong town. Welsh clubs cannot be placed at
all, since the gazetteer is English MSOAs; Merthyr Town is reported, not
guessed.

```bash
python3 scripts/place_clubs.py validate          # the table above
python3 scripts/place_clubs.py authorities 6     # which authorities qualify
python3 scripts/place_clubs.py place clubs.tsv > club_roster.csv
```

The `place` input is one club per line, tab separated:

```
canonical_name <TAB> local_authority <TAB> tier <TAB> division <TAB> ground_name
```

## What the roster will and will not change

It adds **competitors, not candidates**. A club with no `standings` rows
cannot have a Football League ceiling, so `prospects.candidates()` will never
return one. What changes is every existing candidate's catchment and contest
ratio, and the direction is known in advance: catchments fall and contest
ratios rise, most for the clubs with the most non-league neighbours. Whether
that reorders the bands is the question the roster exists to answer.

## Also outstanding: the stale sixth-tier labels

Forty-four clubs in `club_master` carried `current_tier = 6`, a label set
when they were last in the sixth tier and never revisited. Since the previous
commit made `current_tier` load-bearing, each stale one is a club pulling at
a step-2 weight from a ground three divisions lower.

Seven were settled by search and are corrected in this commit:

| Club | was | now | Where they actually play |
|---|---|---|---|
| Alfreton Town | 6 | 7 | Northern Premier League Premier, step 3 |
| Bath City | 6 | 7 | Southern League Premier, step 3 — relegated from the South |
| Eastbourne Borough | 6 | 7 | Isthmian League Premier, step 3 — relegated from the South |
| Hyde United | 6 | 7 | Northern Premier League Premier, step 3 |
| Droylsden | 6 | 9 | North West Counties Premier, step 5 |
| Northwich Victoria | 6 | 9 | Midland League Premier, step 5 |
| Histon | 6 | 9 | United Counties Premier South, step 5 |

Droylsden, Northwich Victoria and Histon are the ones that were costing the
most: a step-5 club was pulling at weight 2.0 against a true 0.5, four times
harder than it should, on three of its neighbours' towns.

Of the thirty-seven still labelled `6`, twenty are corroborated as sixth-tier
by the two division line-ups above. **Seventeen remain unverified**: Bradford
Park Avenue, Canvey Island, Dartford, Farsley Celtic, Grays Athletic,
Guiseley, Havant & Waterlooville, Hayes & Yeading United, Kettering Town,
King's Lynn Town, Lewes, Nuneaton Town, Oxford City, St Albans City, Stafford
Rangers, Welling United and Weymouth. Farsley Celtic is the clearest warning
among them — one search result has them in the National League North and
another has them refused a step 1–4 licence and relegated to the Northern
Counties East League, which is a four-division disagreement. The FA
allocations document settles all seventeen at once, which is the other reason
to want it.
