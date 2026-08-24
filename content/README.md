# Club stories

One markdown file per club, named by its `club_id` from `club_master.csv`:

```
content/charlton-athletic-fc.md
content/exeter-city-fc.md
```

Each file has two parts, **both optional**: YAML front-matter carrying the
hard facts, and markdown prose in named sections. A club with only facts,
only prose, or nothing at all still renders cleanly — the page just shows
less. Write what you have and come back later.

```markdown
---
founded: 1905
ownership_model: fan_trust
---

## Origins
Formed by workers at the Singer cycle factory...

## Trajectory
The 2013 exile cost them a generation of matchday income...
```

## What goes in the front-matter

Everything here is optional. Facts you record become a **Club facts**
panel on the team page, and automatically place the club on the relevant
[theme pages](../src/content.py) — no tagging needed.

### Origins
| Field | Notes |
|---|---|
| `founded` | Year, e.g. `1905` |
| `origin_type` | `works`, `church`, `pub`, `school`, `civic`, `phoenix`, `other` |
| `origin_note` | Reads after "Formed as …", so write a noun phrase: `"Singers F.C., by employees of the Singer cycle works"` |
| `nickname` | e.g. `"the Posh"` — shown beside the club name on its page, so keep it short |

### Ownership & finance
| Field | Notes |
|---|---|
| `ownership_model` | `fan_trust`, `family`, `benefactor`, `consortium`, `foreign_investment`, `multi_club`, `celebrity_media`, `plc` |
| `owner` | Name of the owner or holding entity |
| `owner_since` | Year |
| `multi_club_group` | e.g. `"City Football Group"` |
| `administration` | List of `{year, month, points_deducted, note}`. `month` is optional but worth finding: seasons run August-May, so a calendar year straddles two of them and only the month says which. Most insolvencies happen between January and May, which is the season ending in that same year - without a month the entry is assumed to fall in the season *starting* that year, and lands a season late. Give a number or a name (`2` or `February`) |
| `points_deductions` | List of `{season_end_year, points, reason}` |
| `drops` | List of `{season, note}` - a promotion/relegation pattern this club appears in on the **The drop** insight page. `season` is the pattern's final season, e.g. `2018` for a relegation completed in 2017/18 - matches automatically against `src/movement.py`'s detected patterns, so a season that doesn't correspond to a real one is silently skipped rather than shown. |
| `rises` | Same shape, for **The rise**. |
| `rivalries` | List of `{opponent, name, note}` - a documented rivalry or derby, shown on this club's facts panel and on the **Rivalries & derbies** insight page. `opponent` is the other club's `club_id`; `name` is optional (omit for an unnamed local rivalry); `note` is the researched story. Write it from either side - if the other club's file also documents the same pairing, the insight page shows the fuller of the two rather than both. |

### Infrastructure & environment
| Field | Notes |
|---|---|
| `stadium` / `stadium_opened` / `capacity` | Current ground |
| `stadium_ownership` | `club`, `council`, `third_party`, `disputed` |
| `pitch_type` | `grass` or `artificial_3g` (3G blocks EFL promotion) |
| `previous_grounds` | List of `{name, years}` |
| `exile` | List of `{venue, seasons, distance_miles}` — playing "home" games elsewhere |
| `ground_grading_denial` | List of `{season_end_year, note}` |

### Lineage
| Field | Notes |
|---|---|
| `phoenix_of` | Predecessor `club_id` or name |
| `predecessor_folded` | Year |

`themes: [taylor-report]` adds theme tags manually, for angles the fields
above can't express.

### Theme pages

Dated fields do double duty. Each theme page draws a trajectory chart of its
clubs and puts a marker on the season the theme's defining event happened —
`administration.year`, `points_deductions.season_end_year`, the first year in
an `exile.seasons` range, and so on. Clicking the marker shows what happened.
Below the chart, each club gets a passage explaining why it's there, composed
from the same facts. **You don't need to write any of that** — filling in the
fields above produces it.

Where the derived passage isn't good enough, override it per theme:

```yaml
theme_notes:
  administration: >
    A longer, hand-written account of what the 2013 insolvency actually
    cost the club.
```

Events that predate the standings data (1993/94) can't be plotted, so they're
listed under the chart with a note instead of being dropped.

Theme intros — the "why is this a theme" paragraph at the top of each theme
page — live in `content/themes/<slug>.md`, one short file per theme.

## The four prose sections

Use these `##` headings. Any you omit simply don't appear; anything under
a heading not on this list is kept and shown at the end.

**`## Origins`** — how and why the club came to exist. Almost every English
club began as a works team, a church side, or a pub team. It explains the
name, the colours and the location.

**`## Trajectory`** — the *off-pitch* causes behind the rise and fall.
Points deductions and non-sporting relegations. Insolvency. Ground-grading
denials that blocked a promotion already won on the pitch. Rule changes
that decided a club's fate — the 1995 Premier League contraction, two-up
two-down with the Conference from 2002/03, parachute payments splitting
the Championship into two leagues in one table.

**`## Ownership & Finance`** — who owns the club and who owns the ground,
which are often not the same and rarely irrelevant. Sale-and-leaseback
deals done to satisfy profitability rules. Benefactor dependence and what
happens when the benefactor loses interest. Wage-to-turnover, not transfer
spend. Fan campaigns, boycotts and trust takeovers.

**`## Infrastructure & Environment`** — the Taylor Report's all-seater
requirement reshaping the top two tiers by 1994/95, and safe standing's
return in 2022. Stadium moves that worked and ones that cost a club its
identity. Exiles and returns. Council landlords. Academy category and the
2012 EPPP. Travel burden — Carlisle to Plymouth is around 400 miles, and
that cost is real. Flooding, and clubs building an identity on
sustainability.

## House style

Aim for the deep, off-pitch, beyond-the-headline story — **less manager
and player drama**, more of what actually shaped the club. Prefer causes
over events: not "they were relegated in 2013" (the tables already say
that) but *why*, and what it cost.

Stick to the documented public record. Where a story involves named
owners, insolvency or disputes, describe transactions, court rulings and
regulatory outcomes rather than characterising anyone's motives, and leave
out contested allegations.

The underlying interest here is British culture read through sport — what
the game's history reveals about the country's humour, class, geography and
grudges, not just its finance and governance. Nicknames and rivalries are
the two richest veins found so far, but neither is the whole of it; keep
watching for others.

A club's nickname is often the richest vein of this kind of story. Peterborough
United's "the Posh" is the model: research where it actually came from
(cross-reference more than one source; nicknames often have competing folk
explanations) and tell that story in Origins, not just the fact of the name
itself. If the true origin is genuinely disputed, say so rather than picking
the tidiest version.

That culture runs on pettiness and rivalry as often as on anything grander,
and it's worth hunting for specifically — a badge changed purely to needle
a neighbour, a nickname born as a terrace insult and then worn with pride,
a chant coined in a pub for the sole purpose of drowning out the away end.
Brighton's "Seagulls" is the second model alongside "the Posh": Crystal
Palace's own rebrand to "the Eagles" gave Brighton fans something to mock,
and "Seagulls, Seagulls" was invented specifically to shout it down before
the club ever adopted it officially. The tell that a story belongs in this
vein isn't that it's flattering — it's that a rival club, a pub, or a
crowd's sense of humour is doing the work, not a marketing department.

Rivalries and derbies are their own category, using the `rivalries` field
(above). A genuine one has a documented cause, not just proximity — two
clubs sharing a county isn't a rivalry unless something actually happened:
a merger or a ground dispute (Exeter City and the old Exeter United), a
promotion race with real needle, an owner who arrived from, or later ran, a
rival club, a chant or nickname born specifically to needle the other side
(Bristol Rovers' "Gasheads," Arsenal's move that founded the Tottenham
rivalry). Don't manufacture heat a club's own history doesn't support — the
nearest club in the table isn't automatically "the rivals," and a fixture
being called a "derby" locally is a starting point for research, not a
substitute for it.
