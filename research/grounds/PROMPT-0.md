This is a research-only session. It is a data drop for another Claude session that will merge your file by hand.

HARD RULES
- Do NOT open, create or merge a pull request, whatever CLAUDE.md in this repo says about PRs. That rule does not apply to this session.
- Do NOT change any file in the repository except the one output file below.
- Do NOT spawn subagents: they share your web-search budget and gain nothing.
- Your session has a budget of 200 WebSearch calls in total. You have 46 clubs, so plan on about 4 searches per club. Use "standard" mode. Write each club's line as soon as it is done, and commit and push every 10 clubs, so the work survives if the budget runs out.
- Some club_ids belong to a dissolved club whose phoenix plays on in its place (for example Hereford United -> Hereford FC, Scarborough -> Scarborough Athletic, Chester City -> Chester FC). Research the club playing this season, keep the club_id as given, and say which club you researched in note.
- If the budget runs out, write the remaining clubs as owner_type "unknown", sources [], and a note starting "NOT RESEARCHED", then commit and push.

OUTPUT
- File: research/grounds/result-0.jsonl (create the folder). One JSON line per club, in the format below.
- Commit it and push to the branch claude/ground-research-0 with: git push -u origin claude/ground-research-0
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
bolton-wanderers-fc | Bolton Wanderers | tier 2 | ground on file: Toughsheet Community Stadium | on file: club | earlier attempt: The 2019 administration sale particulars describe the stadium as a long leasehold venue (the training ground is also leasehold), so the club does not appear to own the freehold outright. I could not confirm who holds the
burton-albion-fc | Burton Albion | tier 3 | ground on file: Pirelli Stadium | on file: none
oxford-united-fc | Oxford United | tier 3 | ground on file: Kassam Stadium | on file: third_party
stockport-county-fc | Stockport County | tier 3 | ground on file: Edgeley Park | on file: none
barnet-fc | Barnet | tier 4 | ground on file: The Hive Stadium | on file: club
exeter-city-fc | Exeter City | tier 4 | ground on file: St James Park | on file: council
northampton-town-fc | Northampton Town | tier 4 | ground on file: Sixfields Stadium | on file: council
shrewsbury-town-fc | Shrewsbury Town | tier 4 | ground on file: Croud Meadow | on file: club
barrow-afc | Barrow | tier 5 | ground on file: Holker Street | on file: club
eastleigh-fc | Eastleigh | tier 5 | ground on file: Silverlake Stadium | on file: none
harrogate-town-afc | Harrogate Town | tier 5 | ground on file: Wetherby Road | on file: club
scunthorpe-united-fc | Scunthorpe United | tier 5 | ground on file: Glanford Park | on file: third_party
worthing-fc | Worthing | tier 5 | ground on file: Sussex Transport Community Stadium | on file: none
bedford-town-fc | Bedford Town | tier 6 | ground on file: The Eyrie | on file: none
buxton-fc | Buxton | tier 6 | ground on file: Silverlands | on file: none
chorley-fc | Chorley | tier 6 | ground on file: Victory Park | on file: none
dover-athletic-fc | Dover Athletic | tier 6 | ground on file: Crabble Athletic Ground | on file: none
hampton-and-richmond-borough-fc | Hampton & Richmond Borough | tier 6 | ground on file: Beveree Stadium | on file: none
hemel-hempstead-town-fc | Hemel Hempstead Town | tier 6 | ground on file: Vauxhall Road | on file: none
macclesfield-town-fc | Macclesfield Town | tier 6 | ground on file: Moss Rose | on file: none
merthyr-tydfil-fc | Merthyr Tydfil | tier 6 | ground on file: Penydarren Park | on file: none
salisbury-city-fc | Salisbury City | tier 6 | ground on file: Raymond McEnhill Stadium | on file: none
southport-fc | Southport | tier 6 | ground on file: Haig Avenue | on file: none
torquay-united-fc | Torquay United | tier 6 | ground on file: Plainmoor | on file: none
worksop-town-fc | Worksop Town | tier 6 | ground on file: Windsor Food Park | on file: none
anstey-nomads-fc | Anstey Nomads | tier 7 | ground on file: Cropston Road | on file: none
avro-fc | Avro | tier 7 | ground on file: Whitebank Stadium | on file: none
bath-city-fc | Bath City | tier 7 | ground on file: Twerton Park | on file: club
brentwood-town-fc | Brentwood Town | tier 7 | ground on file: The Brentwood Centre | on file: none
bury-town-fc | Bury Town | tier 7 | ground on file: Ram Meadow | on file: none
cheshunt-fc | Cheshunt | tier 7 | ground on file: The Stadium | on file: none
cray-wanderers-fc | Cray Wanderers | tier 7 | ground on file: Flamingo Park | on file: none
eastbourne-borough-fc | Eastbourne Borough | tier 7 | ground on file: Priory Lane | on file: none
fc-united-of-manchester-fc | FC United of Manchester | tier 7 | ground on file: Broadhurst Park | on file: none
gosport-borough-fc | Gosport Borough | tier 7 | ground on file: Privett Park | on file: none
hanworth-villa-fc | Hanworth Villa | tier 7 | ground on file: Rectory Meadow | on file: none
ilkeston-town-fc | Ilkeston Town | tier 7 | ground on file: New Manor Ground | on file: none
leek-town-fc | Leek Town | tier 7 | ground on file: The F Ball Community Stadium Harrison Park | on file: none
maldon-and-tiptree-fc | Maldon & Tiptree | tier 7 | ground on file: Wallace Binder Ground | on file: none
plymouth-parkway-fc | Plymouth Parkway | tier 7 | ground on file: Bolitho Park | on file: none
ramsgate-fc | Ramsgate | tier 7 | ground on file: Southwood Stadium | on file: none
rushall-olympic-fc | Rushall Olympic | tier 7 | ground on file: Dales Lane | on file: none
stockton-town-fc | Stockton Town | tier 7 | ground on file: The Map Group UK Stadium | on file: none
three-bridges-fc | Three Bridges | tier 7 | ground on file: Jubilee Field | on file: none
welling-united-fc | Welling United | tier 7 | ground on file: Park View Road | on file: none
wingate-and-finchley-fc | Wingate & Finchley | tier 7 | ground on file: The Harry Abrahams Stadium | on file: none
