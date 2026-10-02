This is a research-only session. It is a data drop for another Claude session that will merge your file by hand.

HARD RULES
- Do NOT open, create or merge a pull request, whatever CLAUDE.md in this repo says about PRs. That rule does not apply to this session.
- Do NOT change any file in the repository except the one output file below.
- Do NOT spawn subagents: they share your web-search budget and gain nothing.
- Your session has a budget of 200 WebSearch calls in total. You have 46 clubs, so plan on about 4 searches per club. Use "standard" mode. Write each club's line as soon as it is done, and commit and push every 10 clubs, so the work survives if the budget runs out.
- Some club_ids belong to a dissolved club whose phoenix plays on in its place (for example Hereford United -> Hereford FC, Scarborough -> Scarborough Athletic, Chester City -> Chester FC). Research the club playing this season, keep the club_id as given, and say which club you researched in note.
- If the budget runs out, write the remaining clubs as owner_type "unknown", sources [], and a note starting "NOT RESEARCHED", then commit and push.

OUTPUT
- File: research/grounds/result-2.jsonl (create the folder). One JSON line per club, in the format below.
- Commit it and push to the branch claude/ground-research-2 with: git push -u origin claude/ground-research-2
- When done, reply with one line: how many clubs you established (owner_type not unknown) and how many unknown.

# Ground ownership research brief

You research WHO OWNS THE GROUND of English football clubs, as of now (late 2026; use the most recent reliable information you can find and say how recent it is).

## Tools
- Use WebSearch (mode "standard"; use "extended" only for a club where standard search finds nothing useful). Search result summaries are often enough.
- WebFetch was blocked by the network proxy for every site in an earlier attempt (news, club, council, BBC, Companies House; Wikipedia too). Try it once; if it is blocked, rely on search-result summaries and cite the URLs those results show. Don't waste time retrying fetches.
- Do at least 2 searches per club before giving up, e.g. "<club> <ground> freehold", "<club> stadium owned by", "<club> ground lease council", "<ground> sold".

## Categories (owner_type) - pick exactly one
- `club`: the freehold is held by the club company itself, or by the same corporate group that owns the club (a parent/holding company of the club, so it would pass with the club in a sale).
- `owner_company`: held by the club's owner personally, or by a company the owner controls that is SEPARATE from the club (e.g. a stadium sold to a sister company to help with the finance rules). The key test: if the club were sold, would the ground go with it automatically? If not, it's this.
- `council`: a local authority owns the freehold; the club leases or licenses it.
- `landlord`: any other third party - a private landlord, a former owner, a property company, a pension fund, a university, a school, a charity or community trust, a supporters' trust that is separate from the club.
- `other_club`: the club is a tenant or groundshares at a ground owned by another football or rugby club.
- `unknown`: you could not establish it. Better unknown than a guess.

Set `disputed: true` if ownership is contested, in court, or being forced out.

## Output
Write ONE JSON object per club, one per line (JSON Lines), to the output file named in your task. Fields:

```
{"club_id": "...",                 // exactly as given
 "ground": "...",                  // current home ground name (where they play this season)
 "owner_type": "club|owner_company|council|landlord|other_club|unknown",
 "owner_name": "...",              // who holds the freehold, e.g. "Sunderland City Council", "Walsall FC (Trivela Group)"
 "lease_end": 2128,                // year the club's lease ends, if a tenant and known; else null
 "lease_note": "...",              // e.g. "125-year lease from 2003", "rolling annual licence"; else null
 "since": 2022,                    // year the current arrangement began, if known; else null
 "disputed": false,
 "note": "...",                    // 1-2 plain sentences: the story, especially sale-and-leasebacks, owner-company transfers, council buy-outs, evictions, moves. Facts only.
 "sources": ["https://..."],       // at least one URL you actually saw; two for anything surprising
 "as_of": 2025,                    // year of the newest source you relied on
 "confidence": "high|medium|low",  // high: club/council/primary source or two agreeing reputable reports; medium: one reputable report; low: thin or old
 "on_file_check": "agrees|differs|n/a"  // compare with on_file_ownership in your input (club/council/third_party/disputed): third_party agrees with landlord/owner_company/other_club
}
```

Rules:
- Facts only, no guessing. If sources conflict, prefer the newest and say so in note.
- Write the file as you go (append each club's line when done) so partial work survives.


YOUR CLUBS (club_id | name | tier | ground on file | ownership on file | any earlier attempt's notes)
afc-wimbledon | AFC Wimbledon | tier 3 | ground on file: Plough Lane | on file: club
leyton-orient-fc | Leyton Orient | tier 3 | ground on file: Brisbane Road | on file: third_party
reading-fc | Reading | tier 3 | ground on file: Select Car Leasing Stadium | on file: club | earlier attempt: In 2017-18 the stadium was sold for £24.5m to Prestige Fortune Asia Limited, a company owned by Dai Yongge, which separated it from the club. The May 2025 takeover by Redwood Holdings included the stadium and Bearwood Pa
wycombe-wanderers-fc | Wycombe Wanderers | tier 3 | ground on file: Adams Park | on file: third_party
crawley-town-fc | Crawley Town | tier 4 | ground on file: Broadfield Stadium | on file: council
gillingham-fc | Gillingham | tier 4 | ground on file: Priestfield Stadium | on file: third_party
rotherham-united-fc | Rotherham United | tier 4 | ground on file: New York Stadium | on file: third_party
tranmere-rovers-fc | Tranmere Rovers | tier 4 | ground on file: Prenton Park | on file: club
boston-united-fc | Boston United | tier 5 | ground on file: Jakemans Community Stadium | on file: none
forest-green-rovers-fc | Forest Green Rovers | tier 5 | ground on file: The New Lawn | on file: club | earlier attempt: Ecotricity, Dale Vince's company, is the named party in plans to demolish the New Lawn for 95 homes once the club moves to the approved Eco Park stadium near M5 junction 13. Whether the freehold sits with the club or wit
hornchurch-fc | Hornchurch | tier 5 | ground on file: Hornchurch Stadium | on file: none
southend-united-fc | Southend United | tier 5 | ground on file: Roots Hall | on file: third_party
afc-telford-united-fc | AFC Telford United | tier 6 | ground on file: New Bucks Head | on file: none
brackley-town-fc | Brackley Town | tier 6 | ground on file: St James Park | on file: none | earlier attempt: The club has played at St James Park, Churchill Way, since 1974. One search did not establish who holds the freehold, and the search budget ran out before a second.
chesham-united-fc | Chesham United | tier 6 | ground on file: The Meadow | on file: none
darlington-fc | Darlington | tier 6 | ground on file: Blackwell Meadows | on file: none
farnham-town-fc | Farnham Town | tier 6 | ground on file: Memorial Ground | on file: none
hebburn-town-fc | Hebburn Town | tier 6 | ground on file: Hebburn Sports & Social Ground | on file: none
horsham-fc | Horsham | tier 6 | ground on file: Camping World Community Stadium | on file: none
maidstone-united-fc | Maidstone United | tier 6 | ground on file: Gallagher Stadium | on file: none
oxford-city-fc | Oxford City | tier 6 | ground on file: RAW Charging Stadium | on file: none
slough-town-fc | Slough Town | tier 6 | ground on file: Arbour Park | on file: none
spennymoor-town-fc | Spennymoor Town | tier 6 | ground on file: The Brewery FieldSpennymoorCounty Durham | on file: none
walton-and-hersham-fc | Walton & Hersham | tier 6 | ground on file: Elmbridge Sports Hub | on file: none
alfreton-town-fc | Alfreton Town | tier 7 | ground on file: North Street | on file: none
ashton-united-fc | Ashton United | tier 7 | ground on file: Hurst Cross | on file: none
banbury-united-fc | Banbury United | tier 7 | ground on file: Spencer Stadium | on file: none
bishops-stortford-fc | Bishop's Stortford | tier 7 | ground on file: ProKit UK Stadium | on file: none
burgess-hill-town-fc | Burgess Hill Town | tier 7 | ground on file: Leylands Park | on file: none
chatham-town-fc | Chatham Town | tier 7 | ground on file: The Bauvill Stadium | on file: none
chippenham-town-fc | Chippenham Town | tier 7 | ground on file: Hardenhuish Park | on file: none
dartford-fc | Dartford | tier 7 | ground on file: Princes Park | on file: none
enfield-fc | Enfield | tier 7 | ground on file: Hertingfordbury Park | on file: none
gainsborough-trinity-fc | Gainsborough Trinity | tier 7 | ground on file: The Northolme | on file: none
halesowen-town-fc | Halesowen Town | tier 7 | ground on file: The Grove | on file: none
hitchin-town-fc | Hitchin Town | tier 7 | ground on file: Top Field | on file: none
lancaster-city-fc | Lancaster City | tier 7 | ground on file: Giant Axe | on file: none
leiston-fc | Leiston | tier 7 | ground on file: Victory Road | on file: none
needham-market-fc | Needham Market | tier 7 | ground on file: Bloomfields | on file: none
quorn-fc | Quorn | tier 7 | ground on file: Farley Way Stadium | on file: none
redcar-athletic-fc | Redcar Athletic | tier 7 | ground on file: Green Lane | on file: none
st-albans-city-fc | St Albans City | tier 7 | ground on file: Clarence Park | on file: none
stratford-town-fc | Stratford Town | tier 7 | ground on file: The Arden Garages Stadium | on file: none
warrington-rylands-fc | Warrington Rylands | tier 7 | ground on file: Gorsey Lane | on file: none
whitehawk-fc | Whitehawk | tier 7 | ground on file: The Enclosed Ground | on file: none
workington-afc | Workington | tier 7 | ground on file: Borough Park | on file: none
