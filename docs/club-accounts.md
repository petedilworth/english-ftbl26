# Club accounts — how the next 160 clubs get theirs

The site's thinnest data is money. 91 clubs of 355 have any accounts at all,
and the depth falls off a cliff below the fourth tier:

| tier | clubs playing 2026/27 with no accounts |
|---|---|
| 3 | 4 |
| 4 | 5 |
| 5 | 18 |
| 6 | 46 |
| 7 | 87 |

Every existing row was read from a filing by a person. That does not scale to
161 more clubs, so this is the automated route: **more clubs, not more
seasons**, and the latest filings only.

## The hard part is not fetching, it is the join

Companies House knows companies. This project knows clubs. The join between
them is not the name.

Arsenal's accounts are filed by *Arsenal Holdings Limited*. A search for
"Arsenal" returns dozens of companies, one of which is the supporters' trust
and another of which is a car dealer. `src/finances.py` says at the top of the
file why this matters: which legal entity filed changes the answer by tens of
millions, and insolvency starts a new company number altogether.

So a wrong match is worse than no match, and the club → company mapping is a
**reviewed artefact in the repository**, not a lookup done at fetch time.

## The split, and why it is this one

`api.company-information.service.gov.uk` is refused at the agent
environment's proxy, exactly as `en.wikipedia.org` is. So the same division as
the Wikipedia work applies:

| where | what | file |
|---|---|---|
| your machine | fetch, and nothing else | `scripts/fetch_company_candidates.ps1` |
| the repository | every judgement, under test | `scripts/find_club_companies.py` |

The fetch is dumb and repeatable. The scoring is the part that can be wrong
quietly, so it lives where it can be tested and argued with.

## Stage 1 — map clubs to companies

**Your API key stays on your machine.** Register a free one at
`developer.company-information.service.gov.uk`. The script reads it from an
environment variable; it is never written to a file, never committed, and must
not be pasted into the chat.

```powershell
$env:CH_API_KEY = "your-key-here"
python scripts/find_club_companies.py targets > targets.tsv
./scripts/fetch_company_candidates.ps1 -Targets targets.tsv -Out ch-json
Compress-Archive -Path ch-json\* -DestinationPath ch-json.zip
```

251 clubs, about 660 requests, six to eight minutes at the published rate
limit of 600 requests per five minutes. An interrupted run resumes: re-running
skips files that already exist.

Then the scoring, in the repository:

```bash
python3 scripts/find_club_companies.py score ch-json
```

which writes `data/club-companies.tsv` — one row per club with the chosen
company, its status, its SIC codes, the score, the reasons for it, and every
runner-up.

### How a company is scored

Mechanically, in whole points with a reason attached to each, so a mapping can
be argued with rather than trusted:

| signal | why |
|---|---|
| SIC **93120**, activities of sport clubs | the one code that says a company *is* a club rather than something named after one |
| company status `active` | a dissolved predecessor is not the club that files today |
| named "football club" | the strongest naming signal short of the code |
| the entity a person already named | 88 clubs' hand-read accounts record *which* company they came from without its number; that is a person's answer to this exact question, and it settles the row |
| supporters' trust, foundation, academy, ladies, property | each files its own accounts, and each would be the wrong answer |

A row whose best candidate is weak, or whose top two cannot be separated, is
marked **review** and is not used until it has been looked at.

## Stage 2 — fetch the filings

Written once the mapping is reviewed: the latest two accounts filings per
company as iXBRL, which is the machine-readable form.

## Stage 3 — parse and apply

`ix:nonFraction` facts, a candidate set of FRC taxonomy names per field, and
**every file where nothing matched is reported** rather than having the
nearest number taken from it. Machine-read rows carry an `ixbrl_auto` flag, so
they stay distinguishable from hand-collected ones forever, and a machine-read
row fills a blank club — it never replaces a researched one.

## The ceiling, stated here rather than discovered later

Small clubs legally file under the **small-company or micro-entity regime**,
which carries no profit-and-loss account: no turnover, no wages. The site
already has a disclosure state for this and renders it honestly.

Many fan-owned clubs are **Community Benefit Societies**, which file with the
FCA and are not on Companies House at all.

Both are outcomes to record — a club that discloses nothing is a fact about
the club, not a gap in the data — but the figure-bearing coverage this can add
lands mostly in tiers 3 to 5.
