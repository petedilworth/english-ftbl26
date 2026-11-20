<!-- Written against commit 5287bbc (2026-11-19). Status: being considered,
     nothing built. Figures are from england.db at that commit. -->

# A chat assistant on the site

The idea: a box on the site where a reader asks a question in plain words –
"which club is the best value?", "the five least valuable in the Premier
League", "what happens to a club's money when it goes down?" – and gets an
answer from the site's own data.

## The site does not have to move

GitHub Pages stays. A chat needs a secret API key, and a static site cannot
hide one, so a single small function lives elsewhere (a Cloudflare Worker is
the likely choice: free tier, built-in rate limiting, and its database, D1,
is SQLite, so the schema here works unchanged). The site gains one script for
the chat box. If the function fails, only the chat fails.

## What the data can and cannot answer

This decides the design more than the hosting does.

- **There are no valuations.** `src/value.py` says so at the top. The Club
  value page is a score from 14 levers, not a price. A chat asked for a
  club's "value" must say which measure it used: the Value score, turnover,
  or net assets. Each gives a different list.
- **Relegation and money is thin.** Accounts cover the 2023–2025 seasons
  (386 rows). Clubs relegated with turnover in both the year before and the
  year after: 3 from tier 1, 3 from tier 2, 1 from tier 3, 1 from tier 4.
  Nothing "typical" can be said from that. The Money page's parachute
  comparison (second-tier clubs down from the top flight against the rest)
  is the most the data supports.
- **Results, tables, movement, grounds, catchment** are deep and answerable
  across 69 seasons.

The main risk is an answer that sounds sure and is invented. On a site whose
strength is care with facts, one confident wrong number costs more than the
chat is worth. The assistant must say "the data cannot tell you that" when
it cannot.

## Design, if built

- **One assistant, not separate windows.** Windows with only part of the
  data loaded fail as soon as a question crosses topics.
- **Tools that call the site's own code, not free SQL.** `value.assemble`,
  `money.assemble` and the rest already compute what the pages show. If the
  model writes its own SQL, its medians and definitions will drift from the
  pages. Free SQL, read-only, only as a last resort, with the row count it
  rested on shown in the answer.
- **The page you are on is a hint, not a limit.** Opened from a club page,
  the chat starts with that club in view.
- **Every number cites the page it came from**, so a reader can check it.

## Cost

Claude Opus 5.5 is $4 per million input tokens and $20 per million output,
cache reads $0.20 (Anthropic price list, November 2026). With the schema and
instructions cached and two or three tool calls a question, an estimate is
5–10 cents a question – about $50–100 per thousand. Claude Haiku 5.5 is about
a fortieth of that but weaker at reasoning over numbers. Estimates, not
measurements: measure on 50 real questions before choosing.

A public box with no login needs a per-visitor daily limit and a monthly
spending cap set at the API account, not only in code.

## Cheaper alternatives to weigh first

- **New pages instead.** The sample questions are predictable. "Cheapest
  clubs by each measure" and "what relegation does to the accounts" could be
  ordinary pages: tested, free per visit, never invented.
- **A private Claude Project.** For the owner's own questions, the site's
  CSV files in a Claude Project answer most of this today with nothing built.

## Open questions

1. What does "valuation" mean here: the Value score, turnover and net assets,
   or real sale prices (a new data source, and thin)?
2. Who is it for: the owner, site visitors, or the owner first?
3. The README promises no server, no cookies, no analytics. A public chat
   sends visitors' questions to Anthropic and needs some logs to catch abuse.
   Change the promise and say so on the page, or keep it and not build a
   public chat?
4. What monthly spend is acceptable?
