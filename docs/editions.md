# The editions – specification

Five emails a week, one reader, built on the same database as the site.
This is the record of every decision made in planning, the review of
whether they hold together, and the build order. Amend it when a decision
changes; do not let the chat history be the source of truth.

Status: **framework and Friday preview built** (steps 0–2 below); the
reviews and the feature editions are not. `src/digest.py` is the
Monday preview this replaces; its facts functions are reused.

## 1. Schedule

| Day | Edition | Scope |
|---|---|---|
| Fri | Preview | Tiers 1–5, sections ordered Premier League to National League |
| Mon | Review | Tiers 1–2, the weekend just played |
| Tue | Review | Tiers 3–5, the weekend just played plus the *previous* week's midweek games |
| Wed | Catchment | One theme across all clubs, plus one club profiled |
| Thu | Finance | Weekly; repetition accepted once clubs are exhausted |
| Monthly | Picker audit | How well the match-selection scorer did |

- Thin weeks (international break, no qualifying streaks, a repeated
  finance club) still send, shorter, with a line saying why.
- No drift check. Cadence is cut back by hand if it stops being read.
- Data refreshes daily in its own workflow, separate from all sends.

## 2. Friday preview

Three speeds, all in the one email:

- **Long-form** – 2 to 6 matches, chosen by a storyline-score threshold
  rather than a fixed count. Full narrative, two-club position chart,
  both clubs' recent records, and the claim (see §9).
- **Medium** – two sentences and a one-line stat. No chart.
- **Everything else** – every remaining fixture, one line each, grouped by
  division. A two-word tag only where the scorer earned one
  (`fallen giant`, `2 below level`, `top-three clash`, `derby, 0 miles`).

Charts are inline wherever they help. No fixed cap; the size test (§10)
is the only limit. The email opens with a short midweek catch-up block
when there were midweek games.

## 3. Reviews (Mon and Tue)

In order:

1. **The reckoning** – prose against Friday's claims. No verdict labels,
   no running tally. Self-deprecation lives here: name the expectation
   and what happened ("the case rested on Southend's form; Southend lost
   3–0") and let the reader draw the verdict.
2. **Results that moved history** – prose only for results in the top two
   bands (§7).
3. **Score grid** – every result, grouped by division, with a result tag
   where earned and a position-movement column.
4. **Streak watch** – any run, of any length, that is within two games of
   that club's own record for that streak type.
5. **One alternate table** – form since a date, home-only, second half
   only, level-adjusted, and so on. Rotates weekly.

Midweek games in the Tuesday review are up to a week old and are written
as retrospect, never as news. Any streak they mention is recomputed
against today's record, not the record on the night.

Each review links back to the preview it answers; the preview links
forward to both reviews.

## 4. Wednesday catchment

A comparative theme on top, one club profiled below. Themes rotate:
contested grounds (pairs sharing a catchment), football deserts,
large markets in low divisions, overachievers by points per head, this
weekend's longest and shortest away trips.

Population and contest ratio lead. Catchment income spans only
£31,930 to £53,546 across all 331 clubs and is mentioned **only** for
clubs in the top or bottom 5%.

## 5. Thursday finance

Weekly, from `club_finances`: 91 clubs, seasons 2024 and 2025, staff
costs on 89 rows, net debt on 19. Formats: points per £m of wages,
wage-to-turnover ratio, one club's accounts read properly, revenue
against league position. When clubs run out, revisit with a different
framing. Repetition is accepted.

## 6. Picker audit

Monthly edition plus a live page on the site. The scorer is judged on
**table consequence** (did the result change positions, end a streak,
move a promotion or relegation picture) and **historic weight** (did it
produce something rare in the 1959–present record). Goals and margin
are explicitly not a criterion. Reads from the claims ledger (§9).

## 7. Result bands

| Band | Meaning | Treatment |
|---|---|---|
| Historic | An all-time first or best within the 1959–present record | Prose |
| Notable | Best or worst in 10+ years | Prose |
| Of note | Best or worst in 5+ years | Tag only |

## 8. Voice

- **Dry humour only.** No broad comedy.
- Devices in bounds: understatement and litotes, bathos, deadpan
  formality, self-deprecation.
- Applied everywhere: prose, section headers, fixture tags, subject lines.
- **Suppression:** human events – deaths, disasters, tragedies and their
  anniversaries – force a straight tone. Club distress (administration,
  points deductions, winding-up petitions) does not.
- The list of straight dates lives in `content/straight-dates.yml`. It
  starts empty and is added to as events arise.
- Rules, worked examples and banned moves live in `docs/voice.md`, which
  is researched and written **before** any prose generator. British comic
  form is to be researched, not recalled.
- Preferred method: place facts next to each other so the contrast does
  the work; dry connective phrasing on top. Arrangement over adjectives.

## 9. Claims ledger

At preview time each long-form and medium pick writes a record:
the storyline, the scorer's reason, and a **snapshot of both clubs'
position, points, played and live streaks**. The reviews and the audit
read this back. Without the snapshot, table consequence cannot be
computed – the daily refresh overwrites `standings` in place.

Stored under `content/digests/preview/<date>/claims.json`.

## 10. Archive, site, size

- Archive organized **by edition type**: five streams under
  `content/digests/<type>/<date>/`.
- Inline cross-links both ways between a preview and its two reviews.
- The email is complete in itself. Links add depth; nothing in an
  edition requires a click to understand.
- New site pages: the picker audit page. (Full fixture list and annotated
  grid stay in the email – Gmail clips at ~102 KB and a complete week
  renders at roughly 45 KB.)
- **Size test:** any edition over 90 KB of HTML fails the build.
- The site needs an absolute `SITE_URL` setting for email links; every
  page currently links relatively.

## 11. Infrastructure

- `src/editions/` package: `base.py` (an `Edition` with
  `build(conn, date) -> EditionOutput(subject, html, text, images, claims)`),
  one module per edition, a shared runner that sends, archives, persists
  claims and enforces size identically for all five.
- Email templates in `templates/email/` rendered with Jinja2 (already a
  dependency; `digest.py` concatenates strings today).
- Derived tables written by the refresh, not computed at send time:
  `standings_snapshot`, `club_streak_records`, `result_bands`.
- **One workflow, `editions.yml`**, five cron lines; the edition is
  derived from the weekday or passed as a manual input. The refresh
  workflow triggers it via `workflow_run` so they never race.
- One shared concurrency group for anything that commits `england.db`,
  with rebase-and-retry on push (the existing loop in
  `weekly-digest.yml` is the model).
- `deploy-site.yml` must list every workflow that commits, not only
  "Weekly Digest". Deploy after the refresh and after each edition.
- Idempotent sends: an edition writes `sent.json` and refuses to send
  the same date twice.
- `--dry-run` for every edition writes to `preview/`.
- Golden tests from a frozen `tests/fixtures/england-small.db`.
- A `test.yml` running pytest on pull requests; 25 test files exist and
  none run in CI today.
- Pin `requirements.txt`; every line is `>=`.
- `src/fixtures.py` fetches with `verify=False`; route it through
  `download.py` with verification on.
- `src/site_build.py` is 5,010 lines. New pages go in a new module.

## 12. Build order

0. Research British comic form; write `docs/voice.md`.
1. `src/editions/` skeleton, daily refresh workflow, shared concurrency,
   `SITE_URL`, size test, CI.
2. Friday preview on the new framework, with claims and snapshot. Ship
   it and read it before building anything else.
3. Monday and Tuesday reviews, result bands, streak records, alternate
   tables, cross-links.
4. Wednesday catchment.
5. Thursday finance.
6. Picker audit page, then the monthly edition once a month of claims
   exists.

Deferred: rivalry pages (one per pairing, seeded from nearest-rival
data). Rejected: a deductions-adjusted table; an on-this-day section.

## 13. Known tensions

- Five editions designed before one has been read. Step 2 exists to
  find out which decisions above survive a real week.
- Weekly finance will repeat by spring. Accepted.
- Self-deprecation needs something to have been wrong about, and the
  reckoning carries no verdicts. Resolved by phrasing (§3).
- Human-event suppression depends on a file nobody has filled in yet.
