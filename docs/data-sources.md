# Data sources worth adding

Researched October 2026. Free and open only: every source here is Open
Government Licence, public domain, CC0 or CC BY, or is explicitly free for
non-commercial use, and each row says which. "Effort" is a guess at the
work to get a first page out of it. The ranking weighs new insight against
that effort, with a tilt towards sources that validate what the site
already models rather than add a new column.

What the pipeline already pulls, so none of it is new:
[football-data.co.uk](https://www.football-data.co.uk) results and
fixtures (tiers 1–5), [engsoccerdata](https://github.com/jalapic/engsoccerdata)
league results from 1888 (used from 1958/59), [jfjelstul/englishfootball](https://github.com/jfjelstul/englishfootball),
ONS small-area income and population by MSOA, and Companies House accounts
read by hand into `data/club-companies.tsv` and `club_finances`.

## The shortlist, ranked

| # | Source | What it adds | Access | Licence | Effort |
|---|---|---|---|---|---|
| 1 | **Betting odds, shots, corners, cards and referees** already in the football-data.co.uk files | The bookmakers' probability for every match since the early 2000s: which clubs beat the odds, expected points against actual, the luckiest and unluckiest seasons, and the referee a club dreads. Shots and corners give a performance measure the table hides. | Columns B365H/D/A, PSH, HS, AS, HST, HC, HR, Referee in the CSVs the pipeline caches in `data/raw/`; `download.py` keeps only the score. | Free for personal use; the site already relies on it. | Low: parse columns already on disk. |
| 2 | **Indices of Deprivation 2025** (MHCLG) | Seven deprivation domains per neighbourhood – income, employment, health, crime, education, housing, environment – at a finer grain (LSOA) than the income page's MSOAs. "Deprivation around the ground" as a sibling to income, and a crime domain that is not the police's. | [deprivation.communities.gov.uk/download-all](https://deprivation.communities.gov.uk/download-all), CSV, File 7 has every score and rank. Aggregate LSOA to MSOA by population, or map LSOA centroids straight onto the catchment model. | OGL v3. | Low–medium. |
| 3 | **Companies House API: charges, officers, PSCs** | The charges register lists every mortgage and debenture secured on a company, with the lender and the property: the debt behind the ground-ownership page, and who the stadium is pledged to. Officers and persons with significant control give owners and directors from the register, not from the press. | [developer.company-information.service.gov.uk](https://developer.company-information.service.gov.uk/), free key, 600 requests per five minutes. Company numbers are already matched in `data/club-companies.tsv`. | OGL (Crown copyright). | Low: the numbers are matched; one call per club per endpoint. |
| 4 | **Companies House free accounts data product** | Turnover, staff costs and profit as structured iXBRL for every electronically filed set of accounts, monthly. Would replace the hand-read `club_finances` with a pipeline, and cover the lower tiers the hand reading never reached. | [download.companieshouse.gov.uk/en_accountsdata.html](https://download.companieshouse.gov.uk/en_accountsdata.html), monthly zips of iXBRL. Filter by the matched company numbers. | OGL. | Medium: iXBRL parsing, and small companies file abridged accounts without turnover. |
| 5 | **HM Land Registry: UK companies that own property** (formerly CCOD) | The registered proprietor of every title held by a UK company, with the address and price paid: the authoritative answer to "who owns the ground", title by title. Would turn the researched `grounds.yml` from reporting into record. | [use-land-property-data.service.gov.uk/datasets/ccod](https://use-land-property-data.service.gov.uk/datasets/ccod), monthly CSV, free account. Match by stadium address or postcode. | Free, but under HM Land Registry's own licence, not OGL: check the terms allow republishing the proprietor's name before publishing. | Medium: address matching. |
| 6 | **ONS house prices for small areas** (HPSSA dataset 2) | Median price paid by MSOA, quarterly since 1995. House prices around the ground beside income; and, since it runs back thirty years, whether a club's rise or fall moved the price of the streets around it. | [ONS HPSSA](https://www.ons.gov.uk/peoplepopulationandcommunity/housing/bulletins/housepricestatisticsforsmallareas/yearendingjune2022), xlsx download, same MSOA codes as the income table. | OGL. | Low. |
| 7 | **Census 2021 by MSOA** via Nomis | Age structure, car availability, occupation, country of birth, per neighbourhood. An ageing-town index for catchments (Blackpool against Brighton), and car access for how fans reach the ground. | [Nomis API](https://www.nomisweb.co.uk/) JSON, free, no key for public tables; or [data.gov.uk MSOA extracts](https://ckan.publishing.service.gov.uk/dataset/2662a62f-033f-4105-92f7-26aa5d80f240). | OGL. | Low. |
| 8 | **Wikimedia pageviews API** | Daily page views for every club's Wikipedia article since 2015: an attention index. The hatred page's "exposure" is modelled from geography; this is measured. Spikes on takeover and relegation days are their own story. | [wikimedia.org/api/rest_v1](https://wikimedia.org/api/rest_v1/) per-article endpoint, no key, 100 requests a second. The repo already maps clubs to articles in `data/wikipedia-club-articles.tsv`. | Pageview counts are CC0. | Low. |
| 9 | **data.police.uk street-level crime** | Every recorded crime within a mile of a point, by month, since 2010. Match-day crime against non-match-day around each ground; which grounds' surroundings change most on a Saturday. | [data.police.uk/docs](https://data.police.uk/docs/), no key, 15 requests a second, also monthly CSV dumps. | OGL v3. | Medium: match-day attribution needs the fixture dates, which the site has. |
| 10 | **engsoccerdata `facup` and `playoffs`** | The FA Cup from 1871 to 2016, with venues and attendances for semi-finals and finals, and every play-off since 1987. Giant-killings by tier gap; the play-off curse; a cup record the site has no trace of. | Same raw GitHub files the pipeline already fetches; `facup.csv` and `playoffs.csv` beside `england.csv`. | Free for non-commercial use, cite Curley (2016). The site already relies on it. | Low. |
| 11 | **openfootball eng-england** | Fixtures and results for tiers 1–4 in a public-domain JSON/text format, maintained season by season. A second source to cross-check football-data.co.uk, and the only public-domain one. | [github.com/openfootball/eng-england](https://github.com/openfootball/eng-england) and football.json raw URLs. | Public domain. | Low. |
| 12 | **ORR estimates of station usage** | Entries and exits at every station since 1997. Distance from each ground to its nearest station and how busy it is: which grounds you can reach by train, and the away days that cannot be done without a car. | [dataportal.orr.gov.uk/station-usage](https://dataportal.orr.gov.uk/station-usage), xlsx with coordinates. | OGL. | Low. |
| 13 | **OpenStreetMap via Overpass** | Stadium footprints, capacity tags, and everything near a ground: pubs within 500 m, the nearest station, car parks. "Pubs per ground" writes itself. | [overpass-api.de](https://overpass-api.de/), no key, be gentle with it. | ODbL: attribution required; derived facts are fine, a bulk derived database must be share-alike. | Medium. |
| 14 | **Open-Meteo historical weather** | Hourly weather at any ground on any date since 1940. Rain and temperature per match for sixty years: does it rain more at Burnley, and does the weather move results or the score. | [open-meteo.com](https://open-meteo.com/) historical API, no key, free for non-commercial use, under 10,000 requests a day. | CC BY 4.0. | Low–medium: one request per ground per season of dates. |
| 15 | **Charity Commission register API** | The accounts of every club's community trust – "Burnley FC in the Community" – with income by year. Which clubs' charities are biggest relative to the club. | [api-portal.charitycommission.gov.uk](https://api-portal.charitycommission.gov.uk/hub), free key. | Register data under OGL. | Medium: matching trusts to clubs by name. |
| 16 | **FCA Mutuals Public Register** | Supporters' trusts are community benefit societies; the register holds their rules, annual returns and accounts. The fan-ownership facts, from the regulator. | [mutuals.fca.org.uk](https://mutuals.fca.org.uk), register extract downloadable, documents free. | Public register; check reuse terms. | Medium. |
| 17 | **Historic England NHLE** | Which grounds, stands and gates are listed buildings. A detail for the grounds page: a landlord cannot knock down what is listed. | [historicengland.org.uk open data hub](https://historicengland.org.uk/listing/the-list/data-downloads/), points and polygons. | OGL. | Low. |

## Not open, and why they are not on the list

- **Attendances.** The single most valuable missing variable – it would
  validate the catchment model – and there is no open source for it.
  [englishfootballleaguetables.co.uk](https://englishfootballleaguetables.co.uk/stats/Report/gate/a2011-12.html)
  carries average gates by club and season but states no licence;
  Statista is paid; Transfermarkt and FBref forbid scraping. The one
  legal route is Wikipedia's season articles under CC BY-SA 4.0, with
  attribution and share-alike on anything derived. engsoccerdata's cup
  file has semi-final and final gates only.
- **Transfer fees and squad values.** Transfermarkt only; no open source.
- **Polls of which clubs people dislike.** YouGov publishes ratings pages
  with no API or download licence. The hatred page's survey slot stays
  manual.
- **Google Trends.** No official API; the unofficial clients break and
  the terms do not allow republishing.

## What to do first

1. Parse the odds and match-statistics columns the pipeline already has:
   a page on luck and expected points with no new dependency.
2. Deprivation 2025 onto the catchment model, as its own insight page.
3. Companies House charges and PSCs for the matched companies: the debt
   behind the ground, and the owners from the register.
4. Wikipedia pageviews as the hatred page's measured exposure.

## Backlog

Where each source stands. Updated as work ships; when Phase 1 ships, the
next "Not started" rows are raised again.

| # | Source | Status | Notes |
|---|---|---|---|
| 1 | Odds and match statistics | **Done** (Phase 1a) | `match_stats`, backfilled from 2000/01. The luck page, and expected points and luck beside the current tables on the home page. |
| 2 | Indices of Deprivation 2025 | **Done** (Phase 1b) | Fetched by `.github/workflows/deprivation.yml` into `data/msoa_deprivation.csv`. The deprivation page: nine weight sliders with Solo, map, club ranking and shapes, the tier and income findings. England only. |
| 3 | Companies House: charges, officers, PSCs | **In progress** (Phase 2) | `.github/workflows/companies-house.yml` runs `scripts/fetch_companies_house.py` monthly with the `CH_API_KEY` secret: every club in tiers 1–7, the 73 open matches settled on register evidence where it exists. Writes `data/companies_house.json`. Page next: 'Behind the club'. |
| 4 | Companies House free accounts data | **Planned** (Phase 2) | Only electronically filed accounts are in it; micro-entity accounts carry no turnover. Could fill the value page's finance gap. |
| 5 | Land Registry company-owned titles | Not started | Check the licence allows naming proprietors first. |
| 6 | ONS house prices for small areas | Not started | Same MSOA codes as income; cheap. |
| 7 | Census 2021 by MSOA | Not started | |
| 8 | Wikimedia pageviews | Not started | Measured exposure for the hatred page. |
| 9 | data.police.uk | Not started | |
| 10 | engsoccerdata FA Cup and play-offs | Not started | Same host the pipeline already uses; cheap. |
| 11 | openfootball | Not started | Cross-check only. |
| 12 | ORR station usage | Not started | |
| 13 | OpenStreetMap via Overpass | Not started | ODbL share-alike on bulk derived data. |
| 14 | Open-Meteo | Not started | |
| 15 | Charity Commission | Not started | |
| 16 | FCA mutuals register | Not started | |
| 17 | Historic England NHLE | Not started | |
