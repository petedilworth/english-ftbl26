<!-- Written against commit 44c7df4 (2026-10-29). Coverage figures are from the
     club_finances.csv and data/companies/ files of that commit; re-run them
     before building, because every monthly accounts run moves them. -->

# Money — the comparisons still to build

What the accounts data can now support, and does not yet show anywhere. The
figures behind every item below are already in `club_finances.csv` or the
committed facts (`data/companies/facts/`), so none of them needs a new fetch —
only a page, and the care each item's caveat asks for.

The intended home for most of it is a **Money page**: one place comparing clubs
on money, as the site has pages comparing them on points, grounds and
catchment. Where an item belongs on the team page instead, it says so.

## Coverage, so the page does not promise more than it has

| | rows with it |
|---|---|
| net assets | 261 |
| headcount | 258 |
| cash | 219 |
| fixed-asset cost and depreciation | 175–181 |
| tax owed (HMRC) | 168 |
| turnover | 151 (mostly tiers 1–3) |
| staff costs | 90 |
| money owed to group companies | 43 |
| interest paid | 40 |
| intangible additions | 24 |
| deferred income on its own line | 17 |

Turnover and wages stop at the third tier; the balance sheet reaches all seven.
The Money page has to be built on that shape, not against it: compare the big
clubs on revenue and wages, and every club on the balance sheet. The 101
scanned filings (tiers 1–4 mostly) are the next coverage gain — see the PDF
plan in `docs/club-accounts.md`.

## What blocks the rest of the coverage

- **Fifteen hand-collected rows name no company.** Preston, Stoke,
  Southampton, Ipswich, Carlisle, Newport and others: a row that does not say
  which entity its figures came from cannot be matched to a filing, so neither
  the iXBRL nor the scans can top it up. Recording the entity on each unlocks
  its balance sheet.
- **Six name no level.** A group filing whose hand row does not say "club" or
  "group" gives nothing — Cheltenham, Exeter, Reading, Shrewsbury.
- **23 scanned filings did not read.** See the PDF section of
  `docs/club-accounts.md` for why each kind fails.

## The page

1. **The money league, per tier.** A sortable table: turnover, wages, wages ÷
   turnover, profit, net assets, cash, headcount. Below the third tier it leads
   with the balance sheet, because that is what exists.
2. **The cliff between tiers.** Median turnover and median net assets per
   level. Shows the drop from the Premier League, what a parachute is worth,
   and that the balance sheet keeps falling long after turnover data stops.
3. **Cost per point.** Wages divided by points won in the same season. Only a
   site holding both the accounts and the tables can do this. Full filers only
   — tiers 1–3.
4. **Biggest movers.** The largest year-on-year swings in wages ÷ turnover and
   in net assets. The natural-level page showed the money tells in the year of a
   move, not in a median.
5. **What each club discloses.** By tier: full accounts, small-company,
   micro-entity, the profit-and-loss withheld under section 444 (84 rows), PDF
   only, not on the register. Honest about where the figures stop, and why.

## Single comparisons, each worth a section or a ranked list

- **Going-concern warnings.** 17 filings carry an auditor's material
  uncertainty over going concern — Burnley, Millwall, Sheffield Wednesday,
  Blackpool, Burton, Exeter, Northampton, Peterborough, Reading, Morecambe,
  Bath City. A list with the wording quoted, linked to each filing. The
  strongest single warning a set of accounts carries.
- **Worth less than nothing.** Clubs whose net assets are negative, and by how
  much against turnover where there is one. Common, and not the same thing as
  failing — the next item is what separates them.
- **Who is funding it.** Money owed to group companies (43 rows) and other
  creditors (165, which in small clubs is often a director's loan) against net
  assets. A club with net liabilities and a large intra-group balance is being
  carried by its owner; one with net liabilities and neither is in a different
  position.
- **Short-term solvency.** Cash against creditors due within a year. The
  simplest test of whether the next twelve months are paid for.
- **Owed to HMRC.** Tax owed — PAYE, national insurance, VAT — against
  turnover where there is one, and against cash. HMRC is the creditor that most
  often petitions to wind a football club up, so arrears here matter more than
  their size suggests. Worth a year-on-year column: arrears that grow are the
  warning, not arrears that exist.
- **Investment in the ground and facilities.** Fixed-asset additions in the
  year, and how worn the facilities are: accumulated depreciation as a share of
  cost. A high share is an old ground nobody is spending on. Cross-check
  against the ground-ownership research: a club that does not own its ground
  should have few land-and-buildings assets, and one that does should show them.
- **Season-ticket money.** Deferred income, where it is on its own line (only
  17 rows). Too thin for a ranking; worth a sentence on the clubs that have it.
  Do not substitute the combined accruals line, which also holds costs not yet
  invoiced.
- **Player spending.** Intangible additions (24 rows) against the amortisation
  charge — buying faster than the squad is written down, or slower. Call it
  intangible additions, not transfers: software and licences are in it too.
- **The cost of debt.** Interest paid against bank loans gives an implied rate;
  against turnover, how much of the income goes on servicing debt.
- **Headcount.** Average employees by tier, and wages per employee where both
  exist. The most complete figure the data has after net assets — 258 rows —
  and a plain way to show how small most clubs are.
- **Audited or not.** 67 audited filings, 84 with an accountant's report, 112
  with neither. By tier, it shows where scrutiny stops.
- **Filing on paper.** 1,796 of the 3,101 accounts filings in
  `filings.tsv` were filed on paper — including the full accounts of several
  Premier League clubs. A curiosity, but a true and checkable one.
- **Filing to the deadline.** Clubs file a median of 271 days after their year
  end — the nine-month deadline itself. Late filers stand out, and an overdue
  filing is a warning the register already records. Needs the exact rule (nine
  months, day for day) before naming anyone as late.

## Joins with the rest of the site

- **Balance sheet against natural level.** Do clubs below their level carry
  weaker balance sheets than clubs above it? The wages ÷ turnover version of
  this on the natural-level page found a direction too small to call; net
  assets reach far more clubs and may settle it either way.
- **Money against catchment.** Turnover and net assets per head of catchment
  population: who earns more than their surroundings would predict.
- **Money against the ground.** Fixed assets against capacity and ownership.

## On the team page rather than the Money page

- The balance sheet itself — net assets, cash, short- and long-term creditors,
  headcount — for the 203 small-company rows whose Finances table now says only
  that no profit-and-loss was filed. The figures exist; the table does not show
  them yet.
- The flags the parser sets — `sign_corrected`, `does_not_balance`,
  `ixbrl_ambiguous` — need a line each in `FLAG_LABELS` before any balance-sheet
  figure is shown, so a doubtful figure is never displayed without saying so.
