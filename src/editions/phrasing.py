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

ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 21: "21st", 22: "22nd", 23: "23rd"}


def _ordinal(n: int) -> str:
    return ORDINALS.get(n, f"{n}th")


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
