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

| Club | Buyable | Tenure | The decisive fact |
|---|---|---|---|
| **Maidstone United** | **yes** | **freehold** | Owners actively seeking a majority sale — but have publicly offered to divest the club **while retaining the stadium freehold** |
| **Morecambe** | yes | leasehold_long | Cleanest cap table in the cohort, worst everything else |
| Southport | unknown | leasehold_long | Lease term is not on the public record — the single decisive unknown |
| Macclesfield Town | unknown | freehold | Control moved to a Jersey vehicle; founder hostile and under investigation |
| Torquay United | no | leasehold_long | Consortium not selling; trust's golden share vetoes even the stadium |
| Dagenham & Redbridge | no | unknown | Control settled Feb 2026; KSI stake; a post-hype price |
| Darlington | no | leasehold_short | 91.66% held by a CBS with a 5% individual cap |
| Bury | no | freehold | Holding company has no share capital |
| Hereford United | no | leasehold_long | Trust 50%, Articles cap others at 49% |
| Chester City | no | council | Fan-owned society; funded 2020 bid withdrew over control |
| Rushden & Diamonds | no | leasehold_short | CBS; Nene Park demolished, site still vacant |
| Scarborough | no | council | 100% fan-owned society |

## Maidstone is the one to look at, and the risk is one clause

The only club in the cohort that is **both for sale and freehold**. It is also
the least contested position: Gillingham at 7.4 miles is the *only* club within
20 miles, where Dagenham has four at or above its level inside eight.

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

- **Nine of the twelve ceilings belong to a company that no longer exists.**
  The successor bought a name, not a record. `peak_tier_entity` records this
  and the screen prints it in capitals, because ranking on an inherited ceiling
  prices the wrong club's history.
- **No catchment figures.** `club_catchment` is empty pending
  `msoa_demographics.csv`, so `prospects.py` refuses to produce a ranking. The
  scores shown are on ceiling, fall, recency and tenure only — the free half of
  the thesis.
- Two database defects surfaced and are logged rather than fixed:
  `club_master.current_tier = 0` is wrong for Chester (the successor trades at
  tier 6), and several club ids conflate a dead company with its successor —
  Chester, Darlington, Maidstone, Bury, Hereford, Macclesfield and, separately,
  Dagenham with its pre-merger parent.
