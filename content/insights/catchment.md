Three numbers on every club page here come from a model rather than a count:
how many people the club can draw on, what those people earn, and what share
of them a bigger neighbour is taking. This page is what the model does and
what it cannot do, because none of the three is a measurement and a figure
like *1,856,061* invites more confidence than it has earned.

## Distance ranks clubs backwards

The obvious way to ask how much room a club has is to measure the distance to
its nearest rival, and this site could already do that from the coordinates it
holds. The answer is wrong, and it is wrong in a way that is easy to miss.

**Workington are 54.7 miles from the nearest club in the top four tiers** —
Fleetwood, across the top of England. That is the most isolated position in
this data. **Maidstone are 7.4 miles from Gillingham**, in commuter Kent, and
on that test Maidstone look crowded. But most of Workington's radius is the
Lake District and the Irish Sea, and almost all of Maidstone's is people.
Ranked on distance, Workington win comfortably. Ranked on the thing that
actually fills a ground, they do not.

So the measure here is people, not miles.

## The gravity model

England is divided by the Office for National Statistics into 6,856 Middle
Layer Super Output Areas, small enough to be a neighbourhood and large enough
to be counted properly: **58,620,101 people** between them, each area with a
population-weighted centre.

Every one of those areas is split across *every* club in the data, in
proportion to how strongly each club pulls on it:

```
share(m, c)  =  (A_c / d(m,c)^β)  ÷  Σ_j (A_j / d(m,j)^β)
```

`d` is the distance from the area to the club, `A` is how far that club draws
from, and `β` controls how fast interest falls away with distance. A club's
catchment is then the sum of its shares, weighted by population.

The important word is **split**. Nobody is assigned to a single club. An area
halfway between two clubs of equal size contributes half its people to each,
and an area next door to a big club and forty miles from a small one gives the
big club almost all of it. That is the property a radius count cannot have,
and it is why **Bradford Park Avenue, 3.3 miles from Bradford City, do not get
credited with Bradford**: a radius drawn round Park Avenue contains the city,
but the model asks who those people would actually go to.

Two of the three ingredients are judgement, and they decide the answer:

- **β = 2.** Interest falls with the square of distance. At β = 1 support
  spreads implausibly far; at β = 3 every club becomes purely local and the
  contested measure collapses to nothing.
- **The pull weights**, set by tier and listed below. A Premier League club
  draws from a different radius than a National League one, and the numbers
  encoding that are a choice rather than a finding.

A third guards against arithmetic rather than football: no club is closer than
half a mile to an area, because otherwise a club sitting on top of a centroid
would pull on it infinitely hard.

## Two figures, and the difference between them

Each club is scored twice.

**At the tier it is in now**, which is a fact about today. And **restored to
its historical ceiling**, with every other club held exactly where it is —
what the club would draw if it climbed back to the highest level it has
reached, against the competition it faces in the present.

For most clubs the two are the same number, because most clubs are at or near
their ceiling. Arsenal draw **1,856,061** either way. Where they part company
is the whole point of computing both: **Leyton Orient draw 325,076 in League
One and 1,665,263 restored to the First Division**, because a first-tier club
in east London competes with West Ham and Tottenham on very different terms
than a third-tier one does. Truro are 110,172 now and 159,226 restored.

The club pages lead with the current figure and show the restored one beside
it only when they differ.

## Income

Alongside the population, the same shares are used to weight **net annual
household income** — so a club's figure is the income of the people it would
actually draw, not the average of the areas nearest to it.

**This one is a model on top of a model.** ONS small-area income is not
measured; it is estimated, and published with confidence intervals that are
frequently ±15%. The spread across clubs here runs from about £33,000 to about
£53,000, which is narrower than that uncertainty in places. Read it as a rank
rather than a figure, and do not read small differences at all.

## Contested

The third number asks a different question: not how many people a club could
reach, but how many of the people **closest to it** it actually keeps.

Every area is assigned to whichever club is nearest — its Voronoi cell, the
natural hinterland before anyone competes for it. Of the people in that cell,
the gravity model says what share the club holds. Contested is the rest.

Portsmouth keep 96% of the people nearest to them: **3.6% contested**, the
emptiest position in the data. Marine, in Crosby, keep less than two per cent:
**98.3% contested**, because Liverpool is 7.7 miles away and Everton barely
further.

One detail here is easy to get wrong and this site got it wrong first.
**The share and the cell have to be measured over the same areas.** Comparing
a club's total catchment against the population of its Voronoi cell mixes two
different populations, and it fails in exactly the case that matters: a club
next door to a big one has a tiny cell, so its catchment drawn from further
afield exceeds it, and it scores as *uncontested*. Bradford Park Avenue came
out as having the whole of Bradford to themselves. Restricting both sides of
the ratio to the club's own cell puts them at 51%, which is a description of
sharing a city rather than owning one.

## What this does not cover

**245 of the 345 clubs here have a catchment figure.** The rest have no
coordinates recorded — mostly clubs whose only seasons are old, and twenty
whose local authority is too wide for its centre to stand in for their town.
A club with no coordinates is absent from the model entirely, which is the
right answer: it should not be given a pull it cannot justify.

**Eighty clubs sit at the population-weighted centre of their local authority
rather than at their ground**, because published coordinates for non-league
grounds could not be obtained. Measured against the clubs that *do* have a
surveyed ground, that method lands within a median of 1.6 miles and a worst
case of 8. Distances to those clubs are printed with a `~`.

**The model version is recorded on every row** — `gravity-v1-beta2` — so that
if β or the weights are ever retuned, the figures computed under the old ones
are identifiable rather than quietly replaced.
