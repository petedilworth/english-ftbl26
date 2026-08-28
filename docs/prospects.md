# Acquisition screen: the twelve fallen clubs

Research completed for every club with a Football League ceiling that has
fallen below the fifth tier. The structured conclusions live in
`club_prospects.csv`; this is the reasoning.

## The finding that matters

**Eight of the twelve cannot be bought at any price, and the reason is
structural rather than incidental.**

The thesis assumes distress produces a willing seller. In this cohort it
produced the opposite. A club that fell far enough to be cheap was, in almost
every case, rescued by its own supporters — and those supporters then wrote
constitutions specifically designed to prevent a repeat of what killed it.
Community benefit societies with one-member-one-vote and non-transferable
membership. Articles capping any single holder below control. Asset locks.
Public grant money with community-ownership conditions attached.

Bury is the clearest case: the holding company is **limited by guarantee with
no share capital at all**, so there is no equity instrument in existence to
buy, a sale is prohibited by the Articles, and £1m of Community Ownership Fund
money sits over Gigg Lane. Hereford's trust holds 50% and the Articles cap
anyone else at 49%, so the maximum purchasable stake can never become control.
Chester's model was tested in the market in May 2020 by a funded bidder who was
already a donor to the club; he withdrew within days, saying plainly that he
would not invest without control.

**The distress that creates the discount also creates the lock.** That is a
contradiction inside the thesis, not a run of bad luck, and it should be priced
in before any further research spend.

## Ranked by what actually survived

Catchment is the gravity model's population at the club's *restored* ceiling —
what it would draw if it climbed back — and contest is the share of that a
bigger neighbour takes. Both come from `club_catchment`, and both now include
the 71 sixth- and seventh-tier clubs of the roster, which the model could not
see before. Every figure here is lower than it was.

| Club | Buyable | Tenure | Catchment | Contested | The decisive fact |
|---|---|---|---|---|---|
| **Maidstone United** | **yes** | **freehold** | 205,634 | **56%** | Owners actively seeking a majority sale — but have publicly offered to divest the club **while retaining the stadium freehold** |
| **Morecambe** | yes | leasehold_long | 148,230 | 33% | Cleanest cap table in the cohort, worst everything else |
| Southport | unknown | leasehold_long | 156,797 | 35% | Lease term is not on the public record — the single decisive unknown |
| Macclesfield Town | unknown | freehold | 166,429 | 49% | Control moved to a Jersey vehicle; founder hostile and under investigation |
| Torquay United | no | leasehold_long | 310,511 | **26%** | Consortium not selling; trust's golden share vetoes even the stadium |
| Dagenham & Redbridge | no | unknown | 382,084 | 68% | Control settled Feb 2026; KSI stake; a post-hype price |
| Darlington | no | leasehold_short | 191,694 | 65% | 91.66% held by a CBS with a 5% individual cap |
| Bury | no | freehold | 481,230 | 34% | Holding company has no share capital |
| Hereford United | no | leasehold_long | 316,419 | 36% | Trust 50%, Articles cap others at 49% |
| Chester City | no | council | 146,457 | 61% | Fan-owned society; funded 2020 bid withdrew over control |
| Rushden & Diamonds | no | leasehold_short | 246,004 | 45% | CBS; Nene Park demolished, site still vacant |
| Scarborough | no | council | 93,190 | 60% | 100% fan-owned society |

**The best catchment in the cohort belongs to the club with no share capital,
and the most open one to the club whose trust can veto the stadium.** Bury's
481,230 is Greater Manchester, Torquay's 26% is the emptiest position
anywhere in the twelve, and neither can be bought. That is the contradiction
of the first section restated in numbers.

## Maidstone is the one to look at, and the risk is one clause

The only club in the cohort that is **both for sale and freehold**.

**On distance it looks like open ground and on people it is the opposite, and
this is the single result that justifies having built the catchment model.**
Counting only the fifth tier and above, **Gillingham at 7.4 miles is the only
club within 20 miles of Maidstone**, where Dagenham has four inside eight — so
a screen ranking on distance puts Maidstone first. The gravity model puts
**56% of its catchment in contest, the worst figure of the four clubs that are
buyable or might be**, against Macclesfield's 49%, Southport's 35% and
Morecambe's 33%.

Two things the distance test threw away. It ignored the tiers below: Ebbsfleet,
Grays, Dartford and Canvey Island are all within 17 miles, and the roster adds
**Tonbridge Angels at about seven** — now Maidstone's nearest neighbour of any
kind, and a club this model could not see at all until the FA's allocations
were loaded. And it treated 7.4 miles and 20 miles as the same fact, when
β = 2 means a club four times closer pulls sixteen times harder. The 205,634
people are real; more than half of them have somewhere else to go.

**The roster narrowed the finding without overturning it.** Adding the clubs
below the fifth tier cut every contest ratio, because a club keeps more of a
smaller Voronoi cell, and it cut Maidstone's as hard as anyone's: −19 points,
against Morecambe −19, Southport −16 and Macclesfield −11. Maidstone is still
the most contested of the four, but by **7 points rather than 15**. The
conclusion survives on a thinner margin than the pre-roster numbers implied,
and a reader entitled to one caveat should have that one.

Two things to hold against it. The sellers have said publicly that they would
consider **selling the club while keeping the ground** — which converts the
best tenure in the cohort into the worst, and is on the record as an option
they want. And the ceiling is not theirs: the 1980–92 seasons belong to the
club that resigned from the Football League in 1992 and folded. The company on
sale was incorporated in 1999 and its real ceiling is the fifth tier.

The artificial pitch is a real but deferred cost. It only bites on promotion to
the EFL, two divisions away, and until then it earns community hire income —
the same trade this site has already documented at Sutton and Harrogate.

## Morecambe: buyable and alarming

A single owner holds 100%, with no trust stake and no golden share — the
cleanest structure here. Everything else is a warning. Three National League
embargoes in twelve months, the **first censure ever issued by the Independent
Football Regulator** against a club *and its directors* for withholding
information, unpaid pension contributions, two winding-up petitions over
legacy debts, and an associate of the takeover consortium sanctioned by HM
Treasury. The accounts say survival depends on the owner continuing to fund a
deficit forecast at ~£2m, against sixth-tier revenue.

You would be buying a company whose recent finances you cannot verify, from a
seller who has demonstrated he will not disclose them.

## What the ground research changed

The Gateshead precedent — barred from the 2024 play-offs over ten-season
security of tenure at a council ground, with nothing physically wrong with the
stadium — turned out **not** to bite on most of these. Morecambe has ~109 years
unexpired, Torquay to 2081, Hereford to 2070, Bury owns its freehold outright.

The exceptions are the ones to watch. **Southport's lease term is published
nowhere**, and it decides whether promotion is possible at all. **Darlington
has no primacy of tenure** as a groundshare tenant of a rugby club, has
*already* been barred from a promotion play-off on grading in 2017, and its own
board has concluded that only a new stadium can get it back to the EFL.

## Caveats carried in the data

- **Eight of the twelve ceilings belong to a company that no longer exists.**
  The successor bought a name, not a record. `peak_tier_entity` records this,
  and the screen now ranks on `successor_peak_tier` — the ceiling the company
  actually for sale reached — rather than on the inherited one, because ranking
  on an inherited ceiling prices the wrong club's history. Maidstone's tier-4
  record belongs to the club that folded in 1992; the company on sale has
  reached the fifth. **Dagenham is the exception and was misfiled here at
  first**: its tier-3 ceiling was reached by the live club in 2010/11, and what
  the pre-merger parent inflates is the *length* of the record, not its
  height.
- **The catchment figures are modelled, twice over.** `club_catchment` now
  holds 245 rows from 6,856 MSOAs and 58.6m people, but the population is
  allocated by a Huff gravity model with a judgement-call β and judgement-call
  tier weights (`gravity-v1-beta2`), and the income layer underneath it is ONS
  *modelled* small-area income with intervals often ±15%. The rank order is
  argued with, not read off.
- **Twenty sixth- and seventh-tier clubs are still missing**, four of them in
  the sixth tier, because the ONS gazetteer cannot place a club whose local
  authority is a wide rural one. Their towns are still credited to their
  neighbours. `docs/roster-data.md` names all twenty.
- **Contest ratios before and after the roster are not comparable.** The
  measure asks what share of its own Voronoi cell a club keeps, and adding
  clubs shrinks every cell to a tighter, more local area that its club keeps
  more of. The ordering survived; the level moved for everyone.
- **The two database defects this research surfaced are now fixed.**
  `club_master.current_tier` was `0` for seven clubs whose successors are
  demonstrably playing — and because `catchment.py` reads that column as the
  club's *pull*, a `0` handed the town's population to its neighbours. Chester,
  Macclesfield, Hereford and Scarborough are now `6`, Bury and Workington `7`,
  Rushden & Diamonds `9`; the rebuild moved 291,019 people back to the seven
  towns and reduced the catchment of **156 of the other 158 clubs**, Manchester
  United and Manchester City by about 19,000 each. The screen's Band B no
  longer keys off `current_tier == 0` — that stopped meaning "wound-up company"
  the moment the column was corrected — and reads `peak_tier_entity` instead.
- The second defect is not fixable by a column. **Several club ids conflate a
  dead company with its successor** — Chester, Darlington, Maidstone, Bury,
  Hereford, Macclesfield — so a single id holds two entities' seasons.
  `successor_peak_tier` and `entity_note` carry the distinction the schema
  cannot.
