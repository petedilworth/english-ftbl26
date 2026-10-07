"""
Where every page's data comes from, in one place.

The Sources page (/sources/) is rendered from this registry: each source
says what it supplies, its licence and how often it is refreshed, and
each page lists the sources it draws on. A new page or dataset is added
here, and tests check that every insight page the site builds has an
entry, so the list cannot quietly fall behind the site.

Dates that change - the last result loaded, when the deprivation file was
fetched, the years of the ONS estimates - are filled in at build time by
site_build, not written here.
"""

SOURCES = {
    "football-data": {
        "name": "football-data.co.uk",
        "url": "https://www.football-data.co.uk",
        "what": "Results for tiers 1–5 from 1993/94 (the fifth tier from 2005/06); betting odds, shots, corners, "
                "cards and referees from 2000/01; and the weekend fixture list.",
        "licence": "Free to use; credited in the footer of every page.",
        "refresh": "Daily, by the Refresh workflow; fixtures each Friday.",
    },
    "engsoccerdata": {
        "name": "engsoccerdata (James Curley)",
        "url": "https://github.com/jalapic/engsoccerdata",
        "what": "League results from 1958/59 to 1992/93 for tiers 1–4, the fifth tier from 1979/80 to 2004/05, "
                "and the sixth and seventh tiers from 2012/13 to 2018/19.",
        "licence": "Open data package; cite Curley (2016).",
        "refresh": "Fixed history.",
    },
    "wikipedia-results": {
        "name": "Wikipedia season articles",
        "url": "https://en.wikipedia.org/wiki/English_football_league_system",
        "what": "Sixth- and seventh-tier results from 2019/20, taken from the results grids by hand "
                "(data/nonleague/).",
        "licence": "CC BY-SA 4.0.",
        "refresh": "By hand.",
    },
    "fa-nls": {
        "name": "The FA: National League System allocations",
        "url": "https://www.thefa.com/-/media/thefacom-new/files/competitions/2026-27/nls/nls-1-to-4-club-allocations-2026-27---v1-140526.ashx",
        "what": "Which division each club in steps 1–4 of the non-league system plays in this season.",
        "licence": "Published by The FA.",
        "refresh": "Once a season.",
    },
    "wikipedia-clubs": {
        "name": "Wikipedia club articles",
        "url": "https://en.wikipedia.org/wiki/List_of_football_clubs_in_England",
        "what": "Ground, capacity, colours, founding year and the ground's coordinates, from each club's infobox "
                "(scripts/parse_club_infoboxes.py).",
        "licence": "CC BY-SA 4.0.",
        "refresh": "By hand, when facts are missing.",
    },
    "club-facts": {
        "name": "Club research (content/)",
        "url": "https://github.com/petedilworth/english-ftbl26/tree/main/content",
        "what": "Origins, nicknames, ownership and owners, administrations, rivalries and former grounds, one "
                "file per club, researched by hand from club sites, Wikipedia and local reporting.",
        "licence": "This site's own research.",
        "refresh": "By hand.",
    },
    "club-companies": {
        "name": "Club-to-company matches (data/club-companies.tsv)",
        "url": "https://github.com/petedilworth/english-ftbl26/blob/main/data/club-companies.tsv",
        "what": "Which company each club plays as, scored by name against every similarly named company, with "
                "the runners-up kept; open cases settled only on evidence from the register.",
        "licence": "This site's own work.",
        "refresh": "With each Companies House fetch.",
    },
    "deductions": {
        "name": "Points deductions (points_deductions.csv)",
        "url": "https://github.com/petedilworth/english-ftbl26/blob/main/points_deductions.csv",
        "what": "Every points deduction since 1958/59, each with a source link, mostly to the season's "
                "Wikipedia article.",
        "licence": "This site's own research, sources linked per row.",
        "refresh": "By hand.",
    },
    "finances": {
        "name": "Club accounts (club_finances.csv)",
        "url": "https://find-and-update.company-information.service.gov.uk",
        "what": "Turnover, wages, profit, net debt and revenue streams, read from accounts filed at Companies "
                "House and from results clubs publish, each row with its source link.",
        "licence": "Companies House filings are Crown copyright under the Open Government Licence.",
        "refresh": "By hand, as accounts are filed.",
    },
    "grounds": {
        "name": "Ground ownership research (content/grounds.yml)",
        "url": "https://github.com/petedilworth/english-ftbl26/blob/main/content/grounds.yml",
        "what": "Who owns each ground in tiers 1–7 – the club, the owner's company, the council, a landlord or "
                "another club – with lease lengths, from club statements, council papers and local reporting. "
                "A source for every club.",
        "licence": "This site's own research, sources cited per club.",
        "refresh": "By hand.",
    },
    "hatred": {
        "name": "Dislike research (content/hatred.yml)",
        "url": "https://github.com/petedilworth/english-ftbl26/blob/main/content/hatred.yml",
        "what": "The grievances the record cannot show – a move, a takeover, a scandal – each with a source note.",
        "licence": "This site's own research, sources cited per entry.",
        "refresh": "By hand.",
    },
    "companies-house": {
        "name": "Companies House public data API",
        "url": "https://developer.company-information.service.gov.uk/",
        "what": "For the company each club plays as: status and accounts deadlines, directors, persons with "
                "significant control (followed up through UK parent companies), charges and their lenders, "
                "insolvency cases and accounts filings.",
        "licence": "Crown copyright, Open Government Licence v3.",
        "refresh": "Monthly, by the Companies House workflow.",
    },
    "ons-population": {
        "name": "ONS mid-year population estimates for small areas",
        "url": "https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/populationestimates",
        "what": "People living in each of England's 6,856 neighbourhoods (MSOAs).",
        "licence": "Open Government Licence v3.",
        "refresh": "Yearly, by hand (scripts/build_msoa_demographics.py).",
    },
    "ons-income": {
        "name": "ONS income estimates for small areas",
        "url": "https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/earningsandworkinghours/datasets/"
               "smallareaincomeestimatesformiddlelayersuperoutputareasenglandandwales",
        "what": "Net household income after housing costs for each neighbourhood, with a 95% confidence interval.",
        "licence": "Open Government Licence v3.",
        "refresh": "Every two years, by hand.",
    },
    "ons-geography": {
        "name": "ONS Open Geography Portal",
        "url": "https://geoportal.statistics.gov.uk",
        "what": "Population-weighted centres of each neighbourhood (2021), and the lookup from small areas to "
                "neighbourhoods used to roll up the deprivation scores.",
        "licence": "Open Government Licence v3; contains OS data © Crown copyright and database right.",
        "refresh": "With the census geography.",
    },
    "deprivation": {
        "name": "English Indices of Deprivation 2025 (MHCLG)",
        "url": "https://www.gov.uk/government/statistics/english-indices-of-deprivation-2025",
        "what": "Income, employment, education, health, crime, housing and living-environment scores, and child "
                "and pensioner poverty, for every small area in England (File 7).",
        "licence": "Open Government Licence v3.",
        "refresh": "Every four to five years; fetched by the Deprivation workflow.",
    },
    "osm": {
        "name": "OpenStreetMap",
        "url": "https://www.openstreetmap.org/copyright",
        "what": "The background map tiles, drawn with Leaflet.",
        "licence": "© OpenStreetMap contributors, ODbL.",
        "refresh": "Live.",
    },
    "models": {
        "name": "This site's own models",
        "url": "https://github.com/petedilworth/english-ftbl26/tree/main/src",
        "what": "Figures worked out here rather than published anywhere: the catchment model, expected points "
                "and luck, natural level, and the dislike and value indexes. Each page says how its figures "
                "are made; the code is in src/.",
        "licence": "Modelled, not counted.",
        "refresh": "Every build.",
    },
}

RESULTS = ["football-data", "engsoccerdata", "wikipedia-results", "deductions"]

# Section, then (page title, path from the site root, sources, note).
PAGES = [
    ("The season", [
        ("Home", "index.html", RESULTS + ["fa-nls", "models"],
         "Current tables, with expected points and luck from the betting odds."),
        ("Fixtures", "fixtures/index.html", ["football-data"], ""),
        ("Seasons and divisions", "seasons/index.html", RESULTS + ["fa-nls"], ""),
        ("Weekly emails", "digest/index.html", RESULTS + ["ons-population", "models"],
         "Previews, reviews and the catchment edition."),
    ]),
    ("Clubs", [
        ("Team pages", "teams/index.html",
         RESULTS + ["wikipedia-clubs", "club-facts", "grounds", "finances", "companies-house", "ons-population",
                    "ons-income", "deprivation", "models"],
         "Club facts include the register's company, controller, secured loans and warning lights."),
        ("All clubs, all data", "teams/table/index.html",
         RESULTS + ["wikipedia-clubs", "club-facts", "grounds", "finances", "ons-population", "ons-income",
                    "deprivation", "hatred", "companies-house", "models"],
         "Every column the other pages compute, in one table."),
        ("Compare", "compare/index.html",
         RESULTS + ["wikipedia-clubs", "club-facts", "ons-population", "models"], ""),
        ("Themes", "themes/index.html", ["club-facts", "deductions", "finances"] + RESULTS[:2], ""),
    ]),
    ("Maps and grids", [
        ("The Matrix", "matrix/index.html", RESULTS, ""),
        ("Groundhop Map", "map/index.html", ["wikipedia-clubs", "ons-geography", "osm"] + RESULTS[:2],
         "Clubs without a surveyed ground are placed at their town's population centre."),
    ]),
    ("The story", [
        ("Luck", "insights/luck/index.html", ["football-data", "models"],
         "Expected points from the odds and from shots on target."),
        ("Deprivation around the ground", "insights/deprivation/index.html",
         ["deprivation", "ons-geography", "ons-population", "ons-income", "models"], ""),
        ("Income around the ground", "insights/income/index.html",
         ["ons-income", "ons-population", "ons-geography", "models"], ""),
        ("Catchment population", "insights/catchment/index.html",
         ["ons-population", "ons-geography", "wikipedia-clubs", "models"], ""),
        ("Behind the club", "insights/behind-the-club/index.html", ["companies-house", "club-companies"],
         "Control, charges, directors and warning lights from the register."),
        ("Who owns the ground", "insights/grounds/index.html", ["grounds"], ""),
        ("Which club to buy", "insights/value/index.html",
         RESULTS + ["grounds", "finances", "club-facts", "ons-population", "ons-income", "models"], ""),
        ("The most disliked clubs", "insights/hatred/index.html",
         RESULTS + ["hatred", "finances", "ons-population", "models"], ""),
        ("Yo-yo clubs", "insights/yo-yo/index.html", RESULTS, ""),
        ("Rivalries & derbies", "insights/rivalries/index.html", ["club-facts"] + RESULTS, ""),
        ("Boom and bust", "insights/boom-and-bust/index.html", ["club-facts", "deductions", "finances"] + RESULTS, ""),
        ("Stadium capacity", "insights/capacity/index.html", ["wikipedia-clubs", "club-facts"], ""),
        ("Club finances", "insights/index.html", ["finances"], "Wages, revenue, profit and net debt by season."),
        ("Fallen giants & risers", "insights/fallen-giants/index.html",
         RESULTS + ["ons-population", "ons-income", "models"],
         "Champions who fell, return odds, fastest falls and rises, sleeping giants by catchment size."),
        ("Records, the drop, the rise, points eras, safe thresholds, natural level, timeline, "
         "the pyramid", "insights/index.html", RESULTS + ["models"], "Worked out from the league record."),
    ]),
]


def by_page(sources=SOURCES, pages=PAGES) -> list[dict]:
    """Sections of pages, each page with its sources resolved."""
    return [{"section": section, "pages": [
        {"title": t, "path": p, "note": n, "sources": [dict(sources[k], key=k) for k in keys]}
        for t, p, keys, n in rows]} for section, rows in pages]


def used_by(sources=SOURCES, pages=PAGES) -> dict[str, list[dict]]:
    """For each source, the pages that draw on it."""
    out = {k: [] for k in sources}
    for _section, rows in pages:
        for t, p, keys, _n in rows:
            for k in keys:
                out[k].append({"title": t, "path": p})
    return out
