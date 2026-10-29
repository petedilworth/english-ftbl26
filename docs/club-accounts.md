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

### What the first real run corrected

The concept lists were a starting guess, and `accounts-concepts.tsv` from the
first run showed where they were wrong:

- **Creditors are mostly split by a current / non-current dimension**, three
  times as often as by the maturity dimension the list expected. And matching
  members by substring read long-term debt as short-term, because
  "Non-currentFinancialInstruments" contains the letters of
  "CurrentFinancialInstruments". Members now match exactly.
- **Group filings tag the parent company with no dimension and the group as
  `Consolidated`.** Millwall's net assets read as the holding company's alone.
  Machine-read rows now take the group figures wherever a group files.
- **Restated filings tag figures `Original` and `Revised`.** Sheffield
  Wednesday's 2023 accounts tag every figure Original and read as empty. The
  revision now wins, and an original stands on its own.
- **Some filers drop the minus sign** on a negative figure. The balance sheet
  identities decide the sign uniquely, so it is corrected and flagged
  `sign_corrected`; a balance sheet that still does not add up is flagged
  `does_not_balance` and kept as filed. On the first run, 3 were corrected and
  8 of about 200 do not add up.
- **Totals stated only in their parts** — bank loans within a year plus after —
  are summed, and a total stated whole is never added to its own parts.

Six fields came from the census: debtors, bank loans, money owed to group
companies — how a parent company or an owner funds a club — other creditors,
and the depreciation and amortisation charges from the fixed-asset notes,
which a small company files even when it files no profit-and-loss.

A second pass added nine more, all from concepts the census showed in dozens
of filings: tax owed to HMRC (PAYE, national insurance and VAT — the arrears
behind most winding-up petitions), deferred income where it is on its own line
and the combined accruals-and-deferred-income line kept apart from it, the
fixed-asset note's additions, gross cost and accumulated depreciation, additions
to intangible assets, and interest paid. And each row records whether the
directors chose not to file the profit-and-loss under section 444. The
comparisons these make possible are listed in `docs/future/money.md`.

### Rules that do not bend

- **Nothing a person collected is overwritten.** A hand row keeps every value
  it has. It gains only the columns added after it was written — the balance
  sheet, the headcount — only where blank, only from a filing by **the entity
  the row names**, and only **at the level the row records**. Reading's
  tangible assets are £131,898 for the company and £39.8m for the group with
  the stadium, so a row marked `club` is filled from the company, one marked
  `group` from the group, and one that does not say gets nothing from a group
  filing. Such a row gains `ixbrl_balance_sheet`, and `ixbrl_fill:` names the
  columns the parser wrote, so a corrected reading reaches them next run while a
  value a person enters later is never touched.
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

### Links to the accounts themselves

`data/companies/filings.tsv` lists every accounts filing in the histories the
workflow fetches, with the transaction id Companies House's public site
addresses it by. A team page links the latest filing as the document itself,
and every accounts filing the company has made; each season in its Finances
table links the filing made up in that year — but only for the company that
row is about, so a row read from a holding company is never linked to the
club company's accounts. The links are built from the register's own ids, and
the workflow opens one of each live every month (`check-links`), because this
repository's own environment cannot reach the site to confirm the address.

## The PDF-only filings — the plan

The first run fetched 113 filings that have no iXBRL. The document API offers
them as a PDF and nothing else, so they carry no tagged figures. Its census
(`data/companies/pdf/census.tsv`) overturned the assumption this plan started
from — that they were small clubs' short accounts:

| | |
|---|---|
| PDF-only filings | 113, from 67 clubs |
| scanned paper filings, no text layer | 101 |
| one-page PDFs with a text layer | 12 — not accounts at all, see below |
| tiers 1–4 | 86, median 33 to 40 pages: full audited accounts filed on paper |
| tiers 5–7 | 27, median 5 to 8 pages |

So most of what OCR is for is **big clubs' full accounts**, with a profit-and-loss
account, not small clubs' balance sheets. Many of those clubs already have
press-reported figures here; the scans add the balance sheet, the notes and,
for the clubs with nothing else, the profit-and-loss.

The 12 one-page PDFs were **AA01 forms** — a notice that a company is changing
its accounting date, which Companies House lists under "accounts". Each
displaced a real set of accounts from a club's two fetched filings. The fetch
now skips them.

**Step 1 — get the text out (in the workflow).**
`scripts/read_pdf_accounts.py` records each PDF's pages, whether it has a text
layer and whether it was filed on paper, then gets its text: the text layer
where there is one, tesseract OCR where there is not. The first run read 12
pages of each, and **only 1 of the 79 long filings had its balance sheet inside
them** — Arsenal's contents page puts it on page 23. It now reads every page,
and re-reads any filing an earlier run only part-read: about 3,000 pages at
1.75 seconds each, so two runs of its 70-minute budget.

The OCR is good enough to read figures from. Basingstoke Town's scanned
balance sheet comes through whole, with the misreads OCR makes — "i)" and "Qo"
for a zero — and both years pass every identity in step 2, down to net
liabilities of £230,815.

**Step 2 — built: `scripts/read_pdf_figures.py`.** 78 of the 101 scanned
filings give a balance sheet that adds up, for 48 clubs. Their figures fill 8
club-seasons nobody else had and top up 47 hand-collected rows, under the same
loader and hand-row rules as the iXBRL filings, flagged `pdf_ocr` (and
`pdf_balance_sheet` / `pdf_fill:` on a topped-up hand row). The workflow runs
it every month after OCR.

What the build found, beyond the plan:

- **Candidates, not lines.** OCR moves a subtotal onto the line below — West
  Ham's fixed-asset total comes out on the "Current assets" heading — so each
  figure keeps every candidate value and the identities choose among them.
- **The search must be whole.** Correcting one figure at a time, Gloucester
  City's fixed assets could be nudged to fit a misread total. Searching every
  combination of up to two one-character corrections shows the total was the
  misread figure, and a reading is kept only if exactly one balance sheet adds
  up.
- **Only checked figures are output.** A figure no identity uses — current
  assets where no creditors line was read — proves nothing and is left out.
- **The notes add up too.** Headcount (40 filings) and staff costs (26) come
  from tables whose items must sum to the total printed under them. Where the
  same company's hand-collected row has a wage bill, the scans agree to within
  0.2% for Arsenal, Newcastle, Leicester and Middlesbrough. They differ for
  Derby County by 6.4% — and the filing's own note adds up to the scan's figure,
  not the press's.
- **An independent check.** Each filing prints the year before as its
  comparative column, and that year has its own filing, read separately. Their
  net assets agree in 30 of 32 pairs; the two that differ are restatements,
  marked as such in the later filing.
- **Group and company side by side.** Some groups print both balance sheets
  under one heading, in four columns — Arsenal's "Group Company / 2025 2024
  2025 2024". The first reader took the last two columns, which are the parent
  company's, and gave the group £30,000 in cash. A heading that names both is
  now read as the two balance sheets it is; where the four year columns are not
  there to split it by, the block is refused. A hand row whose level the scan
  no longer supports loses what the parser wrote to it before.

What is still not read: 23 filings — four in an IFRS layout with no "net
current" line (Birmingham City, Manchester United), two balance sheets in one
filing whose headings OCR lost and whose contents page does not settle the
order, and about a dozen whose identities do not hold within one character a
figure.

**Step 2 as planned — read the balance sheet from the text.** A small company's balance
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

**Step 4 — the profit-and-loss of the long filings.** These are full accounts,
so they have one. Its own arithmetic decides acceptance the same way: turnover
less cost of sales is gross profit, gross profit less administrative expenses
and other items is operating profit, and operating profit less net interest is
profit before tax. Staff costs and the average headcount come from the notes,
where every full set of accounts states them.

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
