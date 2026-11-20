# Working conventions for this repo

## Git
- When the work is done, commit and push to main. Never leave a branch
  or pull request for me to merge – I don't review code.
- If you worked on a side branch, merge it into main and push main
  before you finish.
- Before pushing, run this repo's tests or checks. If they fail, fix
  them. If you can't, don't push to main, and tell me why.
- If main publishes a website, check the change at phone width first.

## What this is
As It Stands: English football since 1958/59, tiers 1–7. One SQLite
database (`data/db/england.db`, rebuilt every morning) feeds a static
site on GitHub Pages and five emails a week. No server, no framework,
no cookies, no analytics – keep it that way unless I say otherwise.

## Checks
- Tests: `pip install -r requirements.txt pytest`, then
  `python -m pytest tests/`.
- Site: `python src/site_build.py --no-charts && python -m http.server -d site 8000`.
  Phone width means 320px: the longest club name and every table must fit.
- A push to main that touches `src/`, `templates/`, `static/`, `content/`,
  `club_master.csv` or the database redeploys the site. `docs/` does not.

## Where things are
- `src/site_build.py` builds every page. One module per insight page
  (`src/money.py`, `src/value.py`, `src/luck.py` …), each with its reasons
  in the docstring at the top. Read that first.
- `src/brand.py` holds the name, address and colours. Nothing else should.
- A new type of page needs an entry in `KINDS` in `src/pageindex.py`, or
  `tests/test_pageindex.py` fails.
- Emails: `src/editions/`, voice in `docs/voice.md`.
- Plans not yet built: `docs/future/README.md`.

## Data rules
- Never show an estimate as a fact. Where a club hasn't disclosed a
  figure, record that as a state (`finances.DISCLOSURE`), not a blank.
- There are no sale prices, valuations or attendances in the database.
  The Club value page is a score, not a price. Don't let any page, email
  or summary call it one.
- Accounts cover the 2023–2025 seasons only; turnover and wages mostly
  stop at tier 3. Say how many clubs a median rests on.
- Results data from engsoccerdata is GPL-2.0; see `NOTICE.md` before
  changing how it is redistributed.
