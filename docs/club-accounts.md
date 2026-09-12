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
./scripts/fetch_company_candidates.ps1
Compress-Archive -Path ch-json\* -DestinationPath ch-json.zip
```

The list of clubs to look up is committed at `data/companies/targets.tsv`
(regenerate it with `python3 scripts/find_club_companies.py targets`), so the
fetch needs nothing but PowerShell. 251 clubs, about 1,540 requests, fifteen
minutes at the published rate limit of 600 requests per five minutes. An
interrupted run resumes: re-running skips files that already exist.

### Asking for the club's name does not find the club

The first real run got this wrong, and it is worth recording because the
failure was silent. Every query was the club's name on its own. "Chelsea"
matches 2,772 companies; the advanced search returns them alphabetically and
the plain search by its own relevance, and Chelsea Football Club Limited was
in neither the first 100 nor the first 30. Neither were Liverpool, Reading,
Barnsley or Middlesbrough. The scorer was then choosing the best of a list
that did not contain the answer, which is how a rugby club came to be the
confident match for Middlesbrough.

So the name is qualified before it is sent, and no single query is trusted to
find every club:

| query | finds |
|---|---|
| `<name> football club` | "The Reading Football Club Limited" |
| `<name> fc` | "Burnley FC Holdings Limited", which the first spelling misses |
| `<name>` filtered to SIC 93120 | a club whose name says neither, by cutting thousands of companies down to the sport clubs among them |
| `<name>` on the relevance search | a club whose registered name is nothing like its football one |
| the hand-recorded entity, by name | "Football Ventures (Whites) Limited" is Bolton Wanderers and shares not one word with them |

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
| SIC **93120**, activities of sport clubs | says a company *is* a club rather than something named after one — but not *which sport*, so it never stands alone |
| company status `active` | a dissolved predecessor is not the club that files today |
| named "football club" | the strongest naming signal short of the code |
| the entity a person already named | 88 clubs' hand-read accounts record *which* company they came from without its number; that is a person's answer to this exact question, and it settles the row |
| supporters' trust, foundation, academy, ladies, property | each files its own accounts, and each would be the wrong answer |
| **another sport** — rugby, cricket, golf, gymnastics, tennis | disqualified outright, whatever else it has going for it |
| a name that says nothing about football | disqualified, or at best reviewable: "Chelsea Limited" matches "Chelsea" exactly, and 74 clubs here are named for one common English word |

The last two rows are there because of what the first run produced: **18 of
167 confident matches named another sport** — Middlesbrough Rugby Union
Football Club, Barnsley Gymnastics Club, Woking Golf Club, Darlington Cricket
and Athletic Club. SIC 93120 covers every sport equally, and a rugby club is
constitutionally named a "Rugby Football Club", so the two strongest signals
both fired for the wrong game. "Athletic" stays a football word — Wigan,
Charlton, Oldham — while "athletics" does not.

A row whose best candidate is weak, or whose top two cannot be separated, is
marked **review** and is not used until it has been looked at.

### What the run produced

251 clubs, 1,900 JSON files, and after scoring:

| | |
|---|---|
| confident | 178 |
| to review | 67 |
| no candidate found | 6 |
| **clubs gaining a company that had no accounts at all** | **103** |

Checks that matter more than the counts: all three hand-recorded company
numbers are reproduced exactly; 91% of the 85 hand-recorded entity *names* are
landed on, and every disagreement with one is a review row rather than a
result; no confident match names another sport; and every confident match's
company name contains every word of the club's.

A query that returns nothing writes no file, which is why 290 of the 1,539
queries have no output. That is the `fc` spelling not existing for a given
club, or no sport club of that name carrying SIC 93120 — an empty answer, not
a failure.

## Stage 2 — fetch the filings

Reads the 178 `chosen` rows straight out of `data/club-companies.tsv`, so
again there is nothing to run but PowerShell. The `review` rows are skipped on
purpose: a filing fetched against the wrong company is worse than no filing,
because the figures in it are real and belong to someone else.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$env:CH_API_KEY = "your-key-here"
./scripts/fetch_club_accounts.ps1
Compress-Archive -Path ch-accounts\* -DestinationPath ch-accounts.zip -Force
```

178 companies, about 900 requests, ten to fifteen minutes. Two filings each,
which gives the year-on-year change the club pages already know how to show;
the brief was more clubs, not more history.

Per club it writes the accounts filing history as JSON, and each filing as
`.xhtml` where iXBRL exists or `.pdf` where it does not. **The extension is
the finding.** A scanned PDF carries no tagged figures and cannot be parsed,
and recording that says so, where writing nothing would look like a fetch that
failed.

One wrinkle worth recording, because the obvious spelling fails on every
document: the document API answers with a redirect to a pre-signed S3 URL, and
S3 refuses a request carrying an `Authorization` header alongside its own
signature. So the script follows that redirect by hand, with no credentials on
the second request.

## Stage 3 — parse and apply

`scripts/parse_club_accounts.py`, in the repository, under test.

A filing is an XHTML document with the figures tagged inline:

```xml
<ix:nonFraction name="core:TurnoverRevenue" contextRef="d2024"
                unitRef="GBP" scale="3" sign="-">1,234</ix:nonFraction>
```

The tag says which concept the number is, the context says what period it
covers, and `scale` and `sign` say how to read it — `scale="3"` means the
figure on the page is in thousands, and ignoring it understates a Premier
League turnover by a factor of a thousand with nothing visible to say so. So
the turnover is readable without anyone deciding which number on the page is
turnover, which is the whole difference between this and transcribing a PDF.

What iXBRL does not solve is **which concept name a filer used**. The FRC
taxonomies have been renamed repeatedly and a small company's software may tag
turnover as `TurnoverRevenue`, `TurnoverGrossOperatingRevenue`, or not at all.
Each field therefore carries a candidate set, and every file where none of them
matched is **reported by name, with the concepts it did find**, rather than
filled with the nearest number. That report is what says which spelling to add.

Two rules that do not bend:

- **Nothing hand-collected is overwritten.** The existing rows were read from
  filings by a person and carry notes a parser cannot reproduce. A machine-read
  row fills a club-season that is blank and never replaces a researched one.
- **Every machine-read row carries the flag `ixbrl_auto`**, so which is which
  stays answerable forever rather than for as long as anyone remembers.

```bash
python3 scripts/parse_club_accounts.py ch-accounts          # dry run, reports
python3 scripts/parse_club_accounts.py ch-accounts --apply  # append the rows
```

## The ceiling, stated here rather than discovered later

Small clubs legally file under the **small-company or micro-entity regime**,
which carries no profit-and-loss account: no turnover, no wages. The site
already has a disclosure state for this and renders it honestly.

Many fan-owned clubs are **Community Benefit Societies**, which file with the
FCA and are not on Companies House at all.

Both are outcomes to record — a club that discloses nothing is a fact about
the club, not a gap in the data — but the figure-bearing coverage this can add
lands mostly in tiers 3 to 5.
