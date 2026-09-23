"""
The phrasing layer: facts in, sentences out.

Every word the editions say about a club lives here or in a template in
templates/email/. The facts layer (digest.club_context and friends,
editions/preview.py) never chooses words. That split is what lets the
voice change without the selection logic moving - see docs/voice.md.

These are the neutral originals from digest.py, moved unchanged. The dry
register replaces them after two real editions have been read.
"""

import level as level_mod

def ordinal(n: int | None) -> str:
    """1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st, 93rd, 101st, 111th."""
    if n is None:
        return ""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


_ordinal = ordinal


# ── Narrative ───────────────────────────────────────────────────────────────

def _level_sentence(ctx: dict) -> str | None:
    """
    What kind of club this is, and how far they currently sit from it.

    Composed from the structured fields rather than natural_level_label,
    which is display copy and doesn't decline into a sentence.
    """
    tier, kind = ctx.get("natural_level_tier"), ctx.get("natural_level_kind")
    if not tier or not kind or kind == "insufficient" or tier == level_mod.OUTSIDE:
        return None

    name = ctx["name"]
    here = level_mod.the(tier)

    if kind == "ever-present":
        clause = f"{name} have never played outside {here}"
    elif kind == "established":
        pct = round((ctx.get("natural_level_share") or 0) * 100)
        clause = (f"{name} belong in {here} — {pct}% of their "
                  f"{ctx.get('natural_level_seasons')} recorded seasons")
    elif kind == "yo-yo" and ctx.get("natural_level_second_tier"):
        a, b = sorted([tier, ctx["natural_level_second_tier"]])
        clause = f"{name} live between {level_mod.the(a)} and {level_mod.the(b)}"
    elif kind == "broad":
        clause = (f"{name}'s record runs the length of the pyramid, but its "
                  f"centre of gravity is {here}")
    else:
        clause = f"{name} are, on the balance of their record, a {level_mod.bucket_name(tier)} club"

    # The two directions are not mirror images. Falling below your level is
    # usually structural, so the deficit is the story; climbing above it is
    # usually a moment, so anchor it to when they were last this high
    # rather than implying the club is overachieving on borrowed time.
    gap = ctx.get("natural_level_gap")
    if gap and gap > 0:
        clause += f"; they are {gap} division{'s' if gap > 1 else ''} below that now"
    elif gap and gap < 0:
        up = abs(gap)
        divisions = f"{up} division{'s' if up > 1 else ''} above that"
        since, streak = ctx.get("highest_since"), ctx.get("streak") or 0
        if streak >= 3:
            # Settled at the higher level - the spell is the story, not the
            # single season, and "highest since last year" says nothing.
            clause += f"; they are {streak} seasons into a spell {divisions}"
        elif since and ctx["last_season"] - since >= 2:
            clause += f"; this season is their highest since {since}"
        elif since:
            clause += f"; they are {divisions} this season"
        else:
            clause += "; this season is the highest in their record"
    return clause


def _history_sentence(ctx: dict) -> str:
    name = ctx["name"]
    bits = []
    level_clause = _level_sentence(ctx)
    if level_clause:
        bits.append(level_clause)
    elif ctx["highest_tier"] == 1 and ctx["tier"] >= 3:
        last = ctx["last_tier1_season"]
        bits.append(
            f"{name} are a fallen giant — {ctx['seasons_in_tier1']} top-flight "
            f"season{'s' if ctx['seasons_in_tier1'] != 1 else ''}, the last in {last}, "
            f"now {ctx['tier'] - 1} divisions below"
        )
    elif ctx["yo_yo"] >= 0.25:
        promos, relgs = ctx["promotions"], ctx["relegations"]
        bits.append(
            f"{name} are a classic yo-yo club — {promos} "
            f"promotion{'s' if promos != 1 else ''} and {relgs} "
            f"relegation{'s' if relgs != 1 else ''} since {ctx['first_season']}"
        )
    elif ctx["streak"] >= 10:
        bits.append(
            f"{name} are furniture at this level — {ctx['streak']} consecutive "
            f"seasons and counting"
        )
    else:
        span = ctx["highest_tier"] != ctx["lowest_tier"]
        range_txt = (
            f"between tiers {ctx['highest_tier']} and {ctx['lowest_tier']}"
            if span else f"entirely at tier {ctx['highest_tier']}"
        )
        bits.append(
            f"{name} have spent their {ctx['last_season'] - ctx['first_season'] + 1} "
            f"recorded seasons {range_txt}"
        )
    if ctx["position"]:
        form = f", form {ctx['form']}" if ctx["form"] else ""
        bits.append(
            f"they sit {_ordinal(ctx['position'])} with {ctx['points']} points "
            f"from {ctx['played']} games{form}"
        )
    return "; ".join(bits) + "."


def narrative(fixture: dict, home: dict | None, away: dict | None,
              h2h: dict | None) -> str:
    division = fixture["division_name"]
    # "the Premier League" / "the Championship", but bare "League One" / "League Two"
    division_phrase = division if division.startswith("League") else f"the {division}"
    parts = []
    parts.append(
        f"{fixture['home_name']} host {fixture['away_name']} in "
        f"{division_phrase} on {fixture['date'].strftime('%A %d %B')}."
    )
    for ctx in (home, away):
        if ctx:
            parts.append(_history_sentence(ctx))
    if h2h and home and away:
        first = h2h.get("first_season")
        since = f" since {first - 1}/{first % 100:02d}" if first else ""
        parts.append(
            f"They have met {h2h['total']} times in league play{since}: "
            f"{home['name']} {h2h['a_wins']} wins, {away['name']} {h2h['b_wins']}, "
            f"{h2h['draws']} drawn."
        )
    return " ".join(parts)


# ── Edition-level phrasing ─────────────────────────────────────────────────

def tag_label(tag: tuple) -> str:
    """A fixture-list tag, from the neutral code preview.tags_for produced."""
    kind = tag[0]
    if kind == "followed":
        return "followed club"
    if kind == "derby":
        miles = tag[1]
        return "derby" if miles is None else f"derby, {miles:.0f} miles"
    if kind == "top_clash":
        return "top-three clash"
    if kind == "fallen_giant":
        return "fallen giant"
    if kind == "below_level":
        n = tag[1]
        return f"{n} below level" if n > 1 else "below level"
    if kind == "above_level":
        n = tag[1]
        return f"{n} above level" if n > 1 else "above level"
    if kind == "neighbours":
        return "neighbours"
    if kind == "yo_yo":
        return "yo-yo club"
    if kind == "moved":
        return tag[2].lower().replace("play-off promoted", "promoted") + " last season"
    return ""


def medium_blurb(fixture: dict, home: dict | None, away: dict | None,
                 tags: list[tuple]) -> str:
    """Two sentences: where they stand, and why the fixture made the cut."""
    bits = []
    for ctx in (home, away):
        if ctx and ctx["position"]:
            form = f" ({ctx['form']})" if ctx["form"] else ""
            bits.append(f"{ctx['name']} {_ordinal(ctx['position'])}{form}")
    first = ", ".join(bits) + "." if bits else ""
    reason = ""
    if tags:
        kind = tags[0][0]
        if kind == "fallen_giant":
            reason = f"{tags[0][1]} have played in the top flight."
        elif kind == "below_level":
            reason = "At least one of them sits below where their record says they belong."
        elif kind == "above_level":
            reason = "At least one of them sits above where their record says they belong."
        elif kind == "top_clash":
            reason = "Both in the top three."
        elif kind == "neighbours":
            reason = "Three places or fewer between them."
        elif kind == "derby":
            reason = "Nearest rivals."
        elif kind == "yo_yo":
            reason = "A yo-yo club is involved."
        elif kind == "moved":
            reason = f"{tags[0][1]} were {tags[0][2].lower()} last season."
        elif kind == "followed":
            reason = "A followed club."
    return " ".join(p for p in (first, reason) if p)


def preview_subject(ctx: dict) -> str:
    if ctx["thin"]:
        return f"The week ahead — nothing to preview from {ctx['week_of']:%d %B}"
    return (f"The week ahead — {ctx['fixture_count']} fixtures across "
            f"{ctx['division_count']} divisions from {ctx['week_of']:%d %B}")


def thin_preview(date) -> str:
    return ("No league fixtures fall in the next eight days, which usually "
            "means an international break. Nothing to preview.")


# ── Review phrasing ────────────────────────────────────────────────────────

STREAK_WORDS = {"win": "wins", "loss": "defeats", "draw": "draws", "unbeaten": "games unbeaten",
                "winless": "games without a win", "clean_sheet": "clean sheets",
                "scoreless": "games without scoring"}


def season_label(year: int | None) -> str:
    return "" if year is None else f"{year - 1}/{year % 100:02d}"


def _name(names: dict, club_id: str | None, fallback: str = "") -> str:
    return names.get(club_id, fallback or club_id or "")


def band_tag(band: dict, names: dict) -> str:
    """The short form for a grid row."""
    d, since = band["detail"], band["since"]
    when = f"since {season_label(since)}" if since else "on record"
    kind = band["kind"]
    if kind == "margin":
        return f"biggest win {when}" if d.get("direction") == "win" else f"heaviest defeat {when}"
    if kind == "opponent":
        return f"first win v {_name(names, d.get('opp_id'))} {when}"
    if kind == "streak":
        return f"{d.get('length')} {STREAK_WORDS.get(d.get('streak_type'), '')}, longest {when}"
    if kind == "start":
        return f"{d.get('direction')} start {when}"
    return ""


def band_sentence(band: dict, names: dict) -> str:
    """The long form, for the results that moved history."""
    club = _name(names, band["club_id"])
    d, since = band["detail"], band["since"]
    when = f"since {season_label(since)}" if since else "in their record"
    kind = band["kind"]
    if kind == "margin":
        opp = _name(names, d.get("opp_id"))
        if d.get("direction") == "win":
            return f"{club}'s {d.get('score')} over {opp} was their biggest win {when}."
        return f"{club}'s {d.get('score')} defeat by {opp} was their heaviest {when}."
    if kind == "opponent":
        opp = _name(names, d.get("opp_id"))
        if since:
            return f"{club} beat {opp} for the first time since {season_label(since)}."
        return (f"{club} beat {opp} for the first time on record, "
                f"at the {_ordinal(d.get('meetings_before', 0) + 1)} attempt.")
    if kind == "streak":
        what = STREAK_WORDS.get(d.get("streak_type"), "")
        return f"{club} have {d.get('length')} {what} in a row, their longest run {when}."
    if kind == "start":
        return (f"{club} have {d.get('points')} points from {d.get('games')} games, "
                f"their {d.get('direction')} start {when}.")
    return ""


def reckoning(claim: dict, result: dict | None, now: dict, names: dict) -> str:
    """
    What Friday expected, and what happened. No verdict, no tally: the
    expectation and the outcome side by side, and the reader draws it.
    """
    f = claim["fixture"]
    home, away = f["home_name"], f["away_name"]
    reasons = [tag_label(tuple(r)) for r in claim.get("reasons", [])]
    case = f"Friday's case: {', '.join(r for r in reasons if r)}." if reasons else ""
    if result is None:
        return f"{home} v {away}: no result on file. {case}".strip()
    score = f"{home} {result['hg']}–{result['ag']} {away}."
    moves = []
    for side, club_id in (("home", f["home_id"]), ("away", f["away_id"])):
        snap = (claim.get("snapshot") or {}).get(side) or {}
        then, current = snap.get("position"), (now.get(club_id) or {}).get("position")
        name = f[f"{side}_name"]
        if then and current and then != current:
            moves.append(f"{name} {'up' if current < then else 'down'} from "
                         f"{_ordinal(then)} to {_ordinal(current)}")
        elif then and current:
            moves.append(f"{name} stay {_ordinal(current)}")
    tail = ("; ".join(moves) + ".") if moves else ""
    return " ".join(p for p in (score, case, tail) if p)


def streak_line(s: dict, names: dict) -> str:
    club = _name(names, s["club_id"])
    what = STREAK_WORDS.get(s["streak_type"], s["streak_type"])
    if s["current"] >= s["record"]:
        return (f"{club}: {s['current']} {what} in a row, equalling their record "
                f"({season_label(s['record_season'])}).")
    return (f"{club}: {s['current']} {what} in a row; the record is {s['record']} "
            f"({season_label(s['record_season'])}).")


def alt_table_title(kind: str) -> str:
    return {"home": "Home form only", "away": "Away form only",
            "form": f"The last six"}.get(kind, kind)


def review_subject(ctx: dict) -> str:
    if ctx["thin"]:
        return f"The weekend reviewed — {ctx['label']}: nothing on file yet"
    return f"The weekend reviewed — {ctx['label']}: {ctx['result_count']} results"


def thin_review(label: str) -> str:
    return (f"No results in {label} reached the database this week. Either nothing "
            "was played or the results file has not caught up; the next review "
            "picks them up.")


# ── Catchment phrasing ─────────────────────────────────────────────────────

def division_phrase(name: str) -> str:
    """'the Premier League' and 'the Championship', but bare 'League One'."""
    return name if name.startswith("League") or not name else f"the {name}"


def _people(n: float | None) -> str:
    """Rounded to the thousand: the model does not know a club's catchment to the person."""
    if not n:
        return "none"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} million"
    return f"{round(n, -3):,.0f}"


def _pct(x: float) -> str:
    return f"{round(100 * x)}%"


def _takers_sentence(d: dict, skip: tuple = (), lead: str = "The next biggest draws are") -> str:
    """The biggest other takers - named as the next few, never as 'the rest'."""
    parts = [f"{t['name']} ({_pct(t['pct'])})" for t in d["takers"] if t["club_id"] not in skip]
    if not parts:
        return ""
    return f"{lead} " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + "."


def _fixture_phrase(f: dict, club_id: str) -> str:
    home = f.get("home_id") == club_id
    other = f["away_name"] if home else f["home_name"]
    day = f["date"].strftime("%A")
    return f"They play {other} {'at home' if home else 'away'} on {day}."


def shared_ground(f: dict, home: dict, away: dict) -> dict:
    """
    The fixture whose clubs draw most on each other's doorsteps. Two
    claims, one per doorstep, each stating what the club keeps and what the
    opponent takes - the numbers are the story.
    """
    headline = f"{f['home_name']} v {f['away_name']}: the shared ground"
    paras = []
    for d, other in ((home, away), (away, home)):
        paras.append(
            f"{_people(d['turf'])} people live nearer to {d['name']}'s ground than to any other. "
            f"{d['name']} draw {_pct(d['kept_pct'])} of them; {other['name']} draw "
            f"{_pct(d['opponent_takes'] / d['turf'] if d['turf'] else 0)}. "
            + _takers_sentence(d, skip=(other["club_id"],), lead="The next biggest draws are"))
    paras.append(f"They meet on {f['date']:%A}. On the map, each neighbourhood takes the colour "
                 "of the club that draws most of it.")
    return {"headline": headline, "paragraphs": paras}


def market_section(kind: str, d: dict, f: dict, n_clubs: int, names: dict) -> dict:
    """Bigger or smaller than their division: market rank against pyramid rank."""
    if kind == "bigger":
        headline = f"Bigger than their division: {d['name']}"
    else:
        headline = f"Smaller than their division: {d['name']}"
    paras = [
        f"The model gives {d['name']} {_people(d['catchment'])} people to draw on, the "
        f"{_ordinal(d['market_rank'])} largest market of the {n_clubs} clubs in the top five "
        f"divisions. They sit {_ordinal(d['ladder_rank'])} in the pyramid: "
        f"{_ordinal(d['position'])} in {division_phrase(d['division'])}.",
        f"On their own doorstep, {_people(d['turf'])} people, they draw {_pct(d['kept_pct'])}. "
        + _takers_sentence(d, lead="The next biggest draws are"),
        _fixture_phrase(f, d["club_id"]),
    ]
    return {"headline": headline, "paragraphs": [p for p in paras if p]}


def catchment_subject(ctx: dict) -> str:
    lead = next((s for s in ctx["sections"] if s["kind"] == "shared"), None)
    if lead:
        f = lead["fixture"]
        return f"Catchment — {f['home_name']} v {f['away_name']}, and whose people they are"
    if ctx["sections"]:
        return f"Catchment — {ctx['sections'][0]['text']['headline']}"
    return "Catchment — nothing to map this week"


def thin_catchment_no_fixtures() -> str:
    return "No league fixtures reached the file for the next six days, so there is nothing to tie this week's catchment to."


def thin_catchment_no_model() -> str:
    return "The catchment model has no population data loaded this week, so there is nothing to map."


def thin_catchment_no_story() -> str:
    return ("Every club playing this week has been featured in the last month, or sits where its market "
            "says it should. Nothing new to map.")
