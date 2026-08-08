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
| `administration` | List of `{year, points_deducted, note}` |
| `points_deductions` | List of `{season_end_year, points, reason}` |
| `drops` | List of `{season, note}` - a promotion/relegation pattern this club appears in on the **The drop** insight page. `season` is the pattern's final season, e.g. `2018` for a relegation completed in 2017/18 - matches automatically against `src/movement.py`'s detected patterns, so a season that doesn't correspond to a real one is silently skipped rather than shown. |
| `rises` | Same shape, for **The rise**. |

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

A club's nickname is often the richest vein of this kind of story — British
football culture and humour, not just finance and governance. Peterborough
United's "the Posh" is the model: research where it actually came from
(cross-reference more than one source; nicknames often have competing folk
explanations) and tell that story in Origins, not just the fact of the name
itself. If the true origin is genuinely disputed, say so rather than picking
the tidiest version.
