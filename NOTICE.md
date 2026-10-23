# Licences

Three kinds of thing live in this repository, under three kinds of terms.

## The code – MIT

Everything that runs: `src/`, `scripts/`, `templates/`, `static/`, `tests/`
and `.github/`. Reuse it under the MIT licence in [`LICENSE`](LICENSE).

## The writing and research – CC BY 4.0

The club stories and their facts (`content/*.md`), the insight essays
(`content/insights/`), the theme introductions (`content/themes/`), the ground
ownership research (`content/grounds.yml`), the dislike research
(`content/hatred.yml`), the points-deduction record (`points_deductions.csv`),
the club accounts table (`club_finances.csv`), the takeover research
(`club_prospects.csv`, `docs/`) and the archived emails (`content/digests/`)
are licensed under
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
Reuse them with credit to "English Football History
(github.com/petedilworth/english-ftbl26)" and a link to the licence. Every
source those files cite keeps its own terms; the licence covers this
project's words and arrangement, not the facts or pages behind them.

## Data from others – their own terms

| Data | Where it is here | Terms |
|---|---|---|
| League results from 1958/59 to 1992/93 (tiers 1–4), 1979/80 to 2004/05 (tier 5) and 2012/13 to 2018/19 (tiers 6–7), from [engsoccerdata](https://github.com/jalapic/engsoccerdata) by James Curley | `data/db/england.db` (the `matches` and `standings` tables) and the tables derived from them | GNU GPL, version 2 or later. The licence text is in [`data/LICENSE-engsoccerdata-GPL-2.0.txt`](data/LICENSE-engsoccerdata-GPL-2.0.txt). Cite: Curley, J.P. (2016). engsoccerdata: English Soccer Data 1871-2016. |
| League results and match statistics from 1993/94, from [football-data.co.uk](https://www.football-data.co.uk) | `data/db/england.db` | Published free of charge by football-data.co.uk, credited on every page of the site. Its own terms of use apply. |
| Sixth- and seventh-tier results from 2019/20, and the grounds, capacities, colours and coordinates filled from club infoboxes, from [Wikipedia](https://en.wikipedia.org) | `data/nonleague/`, `club_master.csv`, `data/db/england.db` | Wikipedia's text is CC BY-SA 4.0. These are facts read from it, not its text. |
| Company records from [Companies House](https://find-and-update.company-information.service.gov.uk); population, income and geography from the [Office for National Statistics](https://www.ons.gov.uk); the English Indices of Deprivation 2025 from MHCLG | `data/companies_house.json`, `data/companies/`, `msoa_demographics.csv`, `data/msoa_deprivation.csv`, `data/db/england.db` | Contains public sector information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). Contains OS data © Crown copyright and database right 2026. |
| Which division each non-league club plays in, from The FA's [National League System allocations](https://www.thefa.com) | `data/nls-allocations-2026-27.tsv` | Published by The FA. |
| Map tiles on the site, from [OpenStreetMap](https://www.openstreetmap.org/copyright) | Loaded live, not stored here | © OpenStreetMap contributors, ODbL. |

The site's [Sources page](https://petedilworth.github.io/english-ftbl26/sources/index.html)
says which pages use which of these.
