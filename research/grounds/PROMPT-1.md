This is a research-only session. It is a data drop for another Claude session that will merge your file by hand.

HARD RULES
- Do NOT open, create or merge a pull request, whatever CLAUDE.md in this repo says about PRs. That rule does not apply to this session.
- Do NOT change any file in the repository except the one output file below.
- Do NOT spawn subagents: they share your web-search budget and gain nothing.
- Your session has a budget of 200 WebSearch calls in total. You have 46 clubs, so plan on about 4 searches per club. Use "standard" mode. Write each club's line as soon as it is done, and commit and push every 10 clubs, so the work survives if the budget runs out.
- Some club_ids belong to a dissolved club whose phoenix plays on in its place (for example Hereford United -> Hereford FC, Scarborough -> Scarborough Athletic, Chester City -> Chester FC). Research the club playing this season, keep the club_id as given, and say which club you researched in note.
- If the budget runs out, write the remaining clubs as owner_type "unknown", sources [], and a note starting "NOT RESEARCHED", then commit and push.

OUTPUT
- File: research/grounds/result-1.jsonl (create the folder). One JSON line per club, in the format below.
- Commit it and push to the branch claude/ground-research-1 with: git push -u origin claude/ground-research-1
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
sheffield-united-fc | Sheffield United | tier 2 | ground on file: Bramall Lane | on file: club | earlier attempt: In 2018 reports said Prince Abdullah's bid for sole control hinged on buying the Bramall Lane freehold and related long leaseholds from Kevin McCabe's side of Blades Leisure, so the freehold was then held apart from the 
doncaster-rovers-fc | Doncaster Rovers | tier 3 | ground on file: Eco-Power Stadium | on file: council
plymouth-argyle-fc | Plymouth Argyle | tier 3 | ground on file: Home Park | on file: none
wigan-athletic-fc | Wigan Athletic | tier 3 | ground on file: Brick Community Stadium | on file: council
cheltenham-town-fc | Cheltenham Town | tier 4 | ground on file: Whaddon Road | on file: council
fleetwood-town-fc | Fleetwood Town | tier 4 | ground on file: Highbury Stadium | on file: council
rochdale-fc | Rochdale | tier 4 | ground on file: Crown Oil Arena | on file: club
swindon-town-fc | Swindon Town | tier 4 | ground on file: County Ground | on file: third_party
boreham-wood-fc | Boreham Wood | tier 5 | ground on file: Meadow Park | on file: none
fc-halifax-town | FC Halifax Town | tier 5 | ground on file: The Shay | on file: council
hartlepool-united-fc | Hartlepool United | tier 5 | ground on file: Victoria Park | on file: council
solihull-moors-fc | Solihull Moors | tier 5 | ground on file: Damson Park | on file: none
yeovil-town-fc | Yeovil Town | tier 5 | ground on file: Huish Park | on file: council
billericay-town-fc | Billericay Town | tier 6 | ground on file: New Lodge | on file: none
chelmsford-city-fc | Chelmsford City | tier 6 | ground on file: Melbourne Stadium | on file: none
dagenham-and-redbridge-fc | Dagenham & Redbridge | tier 6 | ground on file: Victoria Road | on file: none
farnborough-town-fc | Farnborough Town | tier 6 | ground on file: ? | on file: none
harborough-town-fc | Harborough Town | tier 6 | ground on file: Bowden Park | on file: none
hereford-united-fc | Hereford United | tier 6 | ground on file: Edgar Street | on file: none
maidenhead-united-fc | Maidenhead United | tier 6 | ground on file: York Road | on file: none
morecambe-fc | Morecambe | tier 6 | ground on file: Mazuma Stadium | on file: none
scarborough-fc | Scarborough | tier 6 | ground on file: McCain Stadium | on file: none
spalding-united-fc | Spalding United | tier 6 | ground on file: Sir Halley Stewart Field | on file: none
truro-city-fc | Truro City | tier 6 | ground on file: Truro City Stadium | on file: none
afc-whyteleafe-fc | AFC Whyteleafe | tier 7 | ground on file: Church Road | on file: none
ap-leamington-fc | AP Leamington | tier 7 | ground on file: ? | on file: none
bamber-bridge-fc | Bamber Bridge | tier 7 | ground on file: Sir Tom Finney Stadium | on file: none
berkhamsted-fc | Berkhamsted | tier 7 | ground on file: Broadwater | on file: none
bromsgrove-rovers-fc | Bromsgrove Rovers | tier 7 | ground on file: Victoria Ground | on file: none
carshalton-athletic-fc | Carshalton Athletic | tier 7 | ground on file: Colston Avenue | on file: none
chichester-city-fc | Chichester City | tier 7 | ground on file: Oaklands Park | on file: none
curzon-ashton-fc | Curzon Ashton | tier 7 | ground on file: Tameside Stadium | on file: none
emley-fc | Emley | tier 7 | ground on file: The Welfare Ground | on file: none
frome-town-fc | Frome Town | tier 7 | ground on file: Badgers Hill | on file: none
guiseley-afc | Guiseley | tier 7 | ground on file: Nethermoor Park | on file: none
havant-and-waterlooville-fc | Havant & Waterlooville | tier 7 | ground on file: Westleigh Park | on file: none
kettering-town-fc | Kettering Town | tier 7 | ground on file: Latimer Park | on file: none
leighton-town-fc | Leighton Town | tier 7 | ground on file: Bell Close | on file: none
malvern-town-fc | Malvern Town | tier 7 | ground on file: Langland Stadium | on file: none
poole-town-fc | Poole Town | tier 7 | ground on file: Tatnam Ground | on file: none
real-bedford-fc | Real Bedford | tier 7 | ground on file: McMullen Park | on file: none
sholing-fc | Sholing | tier 7 | ground on file: Universal Stadium | on file: none
stourbridge-fc | Stourbridge | tier 7 | ground on file: The War Memorial Athletic Ground | on file: none
uxbridge-fc | Uxbridge | tier 7 | ground on file: Honeycroft | on file: none
whitby-town-fc | Whitby Town | tier 7 | ground on file: ? | on file: none
worcester-city-fc | Worcester City | tier 7 | ground on file: Sixways Stadium | on file: none
