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

### Everything in the filing, not four figures from it

The first version read four concepts out of 270 filings and kept nothing else.
The documents are discarded when the Actions job ends, so every field added
after that would have meant fetching them all again. The parser now runs in
two stages:

| stage | reads | writes | needs the documents |
|---|---|---|---|
| `facts` | the fetched filings | `data/companies/facts/<club_id>.tsv` — every tagged fact: concept, period, dimensions, unit, value | yes |
| `rows` | the facts files | `club_finances.csv` | no |

So adding a field, or correcting which concept one is read from, is a re-run of
`rows` anywhere, with no fetch. `data/companies/accounts-concepts.tsv` counts
every concept seen and marks which field reads it; the unread concepts carried
by the most filings are the spellings to add next.

Dimensions matter here, and were invisible before. In the current FRC taxonomy
"creditors due within one year" is not a concept of its own: it is
`core:Creditors` with a maturity dimension, and the same concept with a
different member is the long-term debt. Share capital is `core:Equity` with a
share-capital member, and reading `core:Equity` without checking the member
would put £100 where a club's £254,500 of net assets belongs.

### The small-company rule, corrected

A small-company or micro-entity filing may omit the profit-and-loss account. It
may not omit the balance sheet or the average number of employees. The first
version recorded such a filing as `small_company` and refused every figure on
it, which discarded the balance sheets of 192 non-league filings the law
required them to publish.

The loader (`src/finances.py`) now splits the columns. **Profit-and-loss**
columns are still refused on a `small_company` row. **Balance-sheet and
headcount** columns are accepted on one: employees, fixed, intangible and
tangible assets, current assets, cash, creditors within and after one year, net
current assets, total assets less current liabilities, net assets, share
capital and directors' pay. A row for a club that did not file, or no longer
exists, still carries no figures at all.

Each row also records what the filing says about itself: the accounts type,
whether it was audited, and — read from the text, not a tag — whether the
auditor reported a **material uncertainty over going concern**. Every clean
audit report contains those words negated ("we have not identified any material
uncertainty"), so a match preceded by a negation is not a flag.

### Rules that do not bend

- **Nothing a person collected is overwritten.** A hand row keeps every value
  it has. It gains only the columns added after it was written — the balance
  sheet, the headcount — only where blank, and only from a filing by **the
  entity the row names**, because a holding company and the club company under
  it report different money. Such a row gains the flag `ixbrl_balance_sheet`.
- **Machine-read rows carry `ixbrl_auto` and are rebuilt on every run.** The
  first version skipped any club-season already written, so its turnover-only
  rows could never gain a field. Now they are regenerated from the facts.
- **Facts from a filing no longer fetched are kept.** Each new year's accounts
  push the oldest filing out of the two-filing window, and what was read from it
  is still true. They are dropped only if the club is now matched to a
  different company.

```bash
python3 scripts/parse_club_accounts.py facts ch-accounts    # documents -> facts
python3 scripts/parse_club_accounts.py rows                 # dry run, reports
python3 scripts/parse_club_accounts.py rows --apply         # write the CSV
```

## The PDF-only filings — the plan

109 of the filings fetched have no iXBRL. The document API offers them as a PDF
and nothing else, so they carry no tagged figures. Most are small clubs, and
most of those filed on paper, which Companies House scans: the PDF is a picture
of a page with no text in it.

**Step 1 — find out what they are (in the workflow now).**
`scripts/read_pdf_accounts.py` records, for each PDF, its page count, whether it
has a text layer, and whether it was filed on paper. It gets the text out — from
the text layer where there is one, by OCR (tesseract) where there is not — and
commits it to `data/companies/pdf/`, with `census.tsv` saying what each filing
is and whether its text holds a balance sheet and an employee note. OCR has a
40-minute budget per run; a filing it does not reach is listed as such, and the
next run continues from it.

**Step 2 — read the balance sheet from the text.** A small company's balance
sheet is short and uses the same words in every filing: fixed assets, current
assets, creditors falling due within one year, net current assets, total assets
less current liabilities, creditors falling due after more than one year,
provisions, net assets, called-up share capital, capital and reserves, and the
average number of employees. Each line carries this year's figure and last
year's, brackets for negatives.

**The acceptance rule is arithmetic, not OCR confidence.** A reading is kept
only if the balance sheet adds up:

- fixed assets + current assets − creditors within one year = total assets less
  current liabilities
- current assets − creditors within one year = net current assets
- total assets less current liabilities − creditors after one year − provisions
  = net assets
- net assets = capital and reserves

A single misread digit breaks at least one of these, so a filing whose figures
balance is very unlikely to be misread, and one that does not balance is
recorded as "read, did not balance" rather than half-used. Both years on the
page are checked, which doubles the evidence.

**Step 3 — load them like any other machine-read row,** flagged `pdf_ocr`
rather than `ixbrl_auto`, under the same loader rules and the same protection
for hand-collected rows.

**What stays out.** Profit-and-loss figures from PDFs: small companies do not
file one, and the few that do would need their own arithmetic check (turnover
less costs equals operating profit) before any figure is trusted.

**Beyond Companies House.** Many fan-owned clubs are Community Benefit
Societies, which file annual returns and accounts with the FCA's Mutuals Public
Register rather than with Companies House. That is a separate source with its
own matching problem — club to society number — and a separate piece of work.

## The ceiling, stated here rather than discovered later

Small clubs legally file under the **small-company or micro-entity regime**,
which carries no profit-and-loss account: no turnover, no wages. The site
already has a disclosure state for this and renders it honestly.

Many fan-owned clubs are **Community Benefit Societies**, which file with the
FCA and are not on Companies House at all.

Both are outcomes to record — a club that discloses nothing is a fact about
the club, not a gap in the data — but the figure-bearing coverage this can add
lands mostly in tiers 3 to 5.
