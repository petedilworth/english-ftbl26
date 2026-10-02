This is a research-only session. It is a data drop for another Claude session that will merge your file by hand.

HARD RULES
- Do NOT open, create or merge a pull request, whatever CLAUDE.md in this repo says about PRs. That rule does not apply to this session.
- Do NOT change any file in the repository except the one output file below.
- Do NOT spawn subagents: they share your web-search budget and gain nothing.
- Your session has a budget of 200 WebSearch calls in total. You have 46 clubs, so plan on about 4 searches per club. Use "standard" mode. Write each club's line as soon as it is done, and commit and push every 10 clubs, so the work survives if the budget runs out.
- Some club_ids belong to a dissolved club whose phoenix plays on in its place (for example Hereford United -> Hereford FC, Scarborough -> Scarborough Athletic, Chester City -> Chester FC). Research the club playing this season, keep the club_id as given, and say which club you researched in note.
- If the budget runs out, write the remaining clubs as owner_type "unknown", sources [], and a note starting "NOT RESEARCHED", then commit and push.

OUTPUT
- File: research/grounds/result-3.jsonl (create the folder). One JSON line per club, in the format below.
- Commit it and push to the branch claude/ground-research-3 with: git push -u origin claude/ground-research-3
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
blackpool-fc | Blackpool | tier 3 | ground on file: Bloomfield Road | on file: club | earlier attempt: When Simon Sadler bought 96.2% of Blackpool FC from the High Court receivers in June 2019, ending the Oyston era, he also bought the stadium, the training ground and the hotel company. The stadium appears to be held by B
luton-town-fc | Luton Town | tier 3 | ground on file: Kenilworth Road | on file: none
stevenage-fc | Stevenage | tier 3 | ground on file: Broadhall Way | on file: council
accrington-stanley-fc | Accrington Stanley | tier 4 | ground on file: Wham Stadium | on file: club
crewe-alexandra-fc | Crewe Alexandra | tier 4 | ground on file: Gresty Road | on file: club
grimsby-town-fc | Grimsby Town | tier 4 | ground on file: Blundell Park | on file: none
salford-city-fc | Salford City | tier 4 | ground on file: Peninsula Stadium | on file: club
york-city-fc | York City | tier 4 | ground on file: LNER Community Stadium | on file: council
carlisle-united-fc | Carlisle United | tier 5 | ground on file: Brunton Park | on file: club
fylde-afc | AFC Fylde | tier 5 | ground on file: Mill Farm | on file: none
kidderminster-harriers-fc | Kidderminster Harriers | tier 5 | ground on file: Aggborough | on file: none
tamworth-fc | Tamworth | tier 5 | ground on file: The Lamb Ground | on file: disputed
afc-totton-fc | AFC Totton | tier 6 | ground on file: Testwood Stadium | on file: none
braintree-town-fc | Braintree Town | tier 6 | ground on file: Cressing Road | on file: none
chester-city-fc | Chester City | tier 6 | ground on file: Deva Stadium | on file: none
dorking-wanderers-fc | Dorking Wanderers | tier 6 | ground on file: Meadowbank Stadium | on file: none
folkestone-invicta-fc | Folkestone Invicta | tier 6 | ground on file: Cheriton Road | on file: none
hednesford-town-fc | Hednesford Town | tier 6 | ground on file: Keys Park | on file: none
kings-lynn-town-fc | King's Lynn Town | tier 6 | ground on file: The Walks | on file: none
marine-fc | Marine | tier 6 | ground on file: Marine Travel Arena | on file: none
radcliffe-fc | Radcliffe | tier 6 | ground on file: Stainton Park | on file: none
south-shields-fc | South Shields | tier 6 | ground on file: Mariners Park | on file: none
tonbridge-angels-fc | Tonbridge Angels | tier 6 | ground on file: Longmead Stadium | on file: none
weston-super-mare-fc | Weston-super-Mare | tier 6 | ground on file: The Optima Stadium | on file: none
alvechurch-fc | Alvechurch | tier 7 | ground on file: Lye Meadow | on file: none
aveley-fc | Aveley | tier 7 | ground on file: Parkside | on file: none
basingstoke-town-fc | Basingstoke Town | tier 7 | ground on file: Winklebury Football Complex | on file: none
bracknell-town-fc | Bracknell Town | tier 7 | ground on file: Larges Lane | on file: none
bury-fc | Bury | tier 7 | ground on file: Gigg Lane | on file: none
chertsey-town-fc | Chertsey Town | tier 7 | ground on file: Alwyns Lane | on file: none
cleethorpes-town-fc | Cleethorpes Town | tier 7 | ground on file: The Linden Club | on file: none
dulwich-hamlet-fc | Dulwich Hamlet | tier 7 | ground on file: Champion Hill | on file: none
evesham-united-fc | Evesham United | tier 7 | ground on file: The Spiers & Hartwell Stadium | on file: none
gloucester-city-fc | Gloucester City | tier 7 | ground on file: Meadow Park | on file: none
hanwell-town-fc | Hanwell Town | tier 7 | ground on file: Reynolds Field | on file: none
hyde-united-fc | Hyde United | tier 7 | ground on file: Ewen Fields | on file: none
leatherhead-fc | Leatherhead | tier 7 | ground on file: Fetcham Grove | on file: none
lewes-fc | Lewes | tier 7 | ground on file: The Dripping Pan | on file: none
peterborough-sports-fc | Peterborough Sports | tier 7 | ground on file: The Bee Arena | on file: none
racing-club-warwick-fc | Racing Club Warwick | tier 7 | ground on file: Townsend Meadow | on file: none
redditch-united-fc | Redditch United | tier 7 | ground on file: Valley Stadium | on file: none
stamford-fc | Stamford | tier 7 | ground on file: Zeeco Stadium | on file: none
taunton-town-fc | Taunton Town | tier 7 | ground on file: Wordsworth Drive | on file: none
warrington-town-fc | Warrington Town | tier 7 | ground on file: Cantilever Park | on file: none
wimborne-town-fc | Wimborne Town | tier 7 | ground on file: The Wyatt Homes Stadium | on file: none
yate-town-fc | Yate Town | tier 7 | ground on file: Lodge Road | on file: none
