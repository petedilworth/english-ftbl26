"""
Luck: points won against points expected, two ways.

The odds. The market's price for each match, with the bookmakers' margin
taken out in proportion, gives a probability of a home win, a draw and an
away win. Expected points are 3 x p(win) + p(draw) for each side (with the
season's points rule). The market reprices every week, so a club that
improves mid-season stops looking lucky within a month: the odds measure
surprise against what was known before kick-off, and understate the luck
of a club whose improvement was itself lucky.

The shots. Each side's shots on target, times the share of shots on
target that became goals in that division that season, gives an expected
score; two Poisson distributions turn it into the chance of each result.
This is not expected goals - there is no shot location - and it reads a
match by what happened in it, not by what was expected before it. That
makes the two measures disagree in useful ways.

Luck = actual points - expected points, summed over the matches that have
the data. Nothing here touches points deductions: they are not luck.
"""

import logging
import math
import sqlite3

import numpy as np
import pandas as pd

import aggregate

logger = logging.getLogger(__name__)

MIN_COVERAGE = 0.9          # a season is ranked only if this share of its matches has the data
MIN_MARKET_SEASONS = 8      # to judge whether a club beats the market, not just had a year
MAX_OVERROUND = 1.4         # above this the row is a typo, not a price
MAX_GOALS = 12


def probabilities(h, d, a):
    """Proportional de-vig: implied probabilities scaled to sum to one."""
    inv = np.column_stack([1 / np.asarray(h, float), 1 / np.asarray(d, float), 1 / np.asarray(a, float)])
    total = inv.sum(axis=1)
    ok = (total >= 0.98) & (total <= MAX_OVERROUND)
    p = inv / total[:, None]
    p[~ok] = np.nan
    return p


def poisson_wdl(lam_h, lam_a):
    """P(home win), P(draw), P(away win) for independent Poisson scores."""
    lam_h = np.asarray(lam_h, float)[:, None]
    lam_a = np.asarray(lam_a, float)[:, None]
    k = np.arange(MAX_GOALS + 1)[None, :]
    log_fact = np.array([math.lgamma(i + 1) for i in range(MAX_GOALS + 1)])[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        ph = np.exp(k * np.log(lam_h) - lam_h - log_fact)
        pa = np.exp(k * np.log(lam_a) - lam_a - log_fact)
    ph = np.where(lam_h == 0, (k == 0).astype(float), ph)
    pa = np.where(lam_a == 0, (k == 0).astype(float), pa)
    joint = ph[:, :, None] * pa[:, None, :]
    win = np.tril(np.ones((MAX_GOALS + 1, MAX_GOALS + 1)), -1)
    draw = np.eye(MAX_GOALS + 1)
    pw = (joint * win).sum(axis=(1, 2))
    pd_ = (joint * draw).sum(axis=(1, 2))
    pl = (joint * win.T).sum(axis=(1, 2))
    s = pw + pd_ + pl
    return np.column_stack([pw / s, pd_ / s, pl / s])


def load_matches(conn: sqlite3.Connection) -> pd.DataFrame:
    """Every match with odds or shots, with result and both probability sets."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"matches", "match_stats"} <= tables:
        return pd.DataFrame()
    df = pd.read_sql_query(
        """
        SELECT m.season_end_year AS season, m.tier, m.division_id, m.match_date,
               m.home_club_id AS home, m.away_club_id AS away, m.home_name, m.away_name,
               m.fthg, m.ftag, m.ftr,
               COALESCE(s.mkt_h, s.pin_h, s.b365_h) AS oh, COALESCE(s.mkt_d, s.pin_d, s.b365_d) AS od,
               COALESCE(s.mkt_a, s.pin_a, s.b365_a) AS oa,
               s.home_sot, s.away_sot
        FROM matches m JOIN match_stats s
          ON s.season_end_year = m.season_end_year AND s.tier = m.tier
         AND s.home_name = m.home_name AND s.away_name = m.away_name
         AND (s.division_id = m.division_id OR (s.division_id IS NULL AND m.division_id IS NULL))
        WHERE m.tier <= 5
        """, conn)
    if df.empty:
        return df
    p = probabilities(df["oh"], df["od"], df["oa"])
    df["ph"], df["pd"], df["pa"] = p[:, 0], p[:, 1], p[:, 2]

    # Shots: goals per shot on target in the division that season.
    has = df["home_sot"].notna() & df["away_sot"].notna()
    sot = df[has]
    conv = (sot.groupby(["season", "tier"])[["fthg", "ftag"]].sum().sum(axis=1)
            / sot.groupby(["season", "tier"])[["home_sot", "away_sot"]].sum().sum(axis=1).replace(0, np.nan))
    c = df.set_index(["season", "tier"]).index.map(conv.to_dict()).to_numpy(float)
    lam_h = df["home_sot"].to_numpy(float) * c
    lam_a = df["away_sot"].to_numpy(float) * c
    ok = has.to_numpy() & np.isfinite(lam_h) & np.isfinite(lam_a)
    q = np.full((len(df), 3), np.nan)
    if ok.any():
        q[ok] = poisson_wdl(lam_h[ok], lam_a[ok])
    df["sh"], df["sd"], df["sa"] = q[:, 0], q[:, 1], q[:, 2]

    rules = {key: aggregate.points_rule(int(key[1]), int(key[0]))
             for key in df[["season", "tier"]].drop_duplicates().itertuples(index=False)}
    df["win_h"] = [rules[(s, t)][0] for s, t in zip(df["season"], df["tier"])]
    df["win_a"] = [rules[(s, t)][1] for s, t in zip(df["season"], df["tier"])]
    df["pts_h"] = np.select([df["ftr"] == "H", df["ftr"] == "D"], [df["win_h"], 1], 0)
    df["pts_a"] = np.select([df["ftr"] == "A", df["ftr"] == "D"], [df["win_a"], 1], 0)
    df["xo_h"] = df["win_h"] * df["ph"] + df["pd"]
    df["xo_a"] = df["win_a"] * df["pa"] + df["pd"]
    df["xs_h"] = df["win_h"] * df["sh"] + df["sd"]
    df["xs_a"] = df["win_a"] * df["sa"] + df["sd"]
    return df


def club_seasons(df: pd.DataFrame) -> pd.DataFrame:
    """One row per club per season: points, and points expected each way."""
    if df.empty:
        return pd.DataFrame()
    home = pd.DataFrame({"season": df["season"], "tier": df["tier"], "division_id": df["division_id"],
                         "club_id": df["home"], "name": df["home_name"], "pts": df["pts_h"],
                         "xo": df["xo_h"], "xs": df["xs_h"]})
    away = pd.DataFrame({"season": df["season"], "tier": df["tier"], "division_id": df["division_id"],
                         "club_id": df["away"], "name": df["away_name"], "pts": df["pts_a"],
                         "xo": df["xo_a"], "xs": df["xs_a"]})
    both = pd.concat([home, away], ignore_index=True)
    both = both[both["club_id"].notna()]
    both["has_o"] = both["xo"].notna()
    both["has_s"] = both["xs"].notna()
    both["pts_o"] = both["pts"].where(both["has_o"], 0)
    both["pts_s"] = both["pts"].where(both["has_s"], 0)
    g = both.groupby(["season", "tier", "division_id", "club_id"], dropna=False)
    cs = g.agg(name=("name", "first"), played=("pts", "size"), pts=("pts", "sum"),
               n_o=("has_o", "sum"), xo=("xo", "sum"), pts_o=("pts_o", "sum"),
               n_s=("has_s", "sum"), xs=("xs", "sum"), pts_s=("pts_s", "sum")).reset_index()
    cs["luck_o"] = (cs["pts_o"] - cs["xo"]).where(cs["n_o"] > 0)
    cs["luck_s"] = (cs["pts_s"] - cs["xs"]).where(cs["n_s"] > 0)
    cs["cov_o"] = cs["n_o"] / cs["played"]
    cs["cov_s"] = cs["n_s"] / cs["played"]
    # Expected points over the whole season: actual points where a match has
    # no data, expected where it does, so a few missing prices do not sink a club.
    cs["xpts_o"] = cs["pts"] - cs["luck_o"].fillna(0)
    cs["xpts_s"] = cs["pts"] - cs["luck_s"].fillna(0)
    return cs


def ranked(cs: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Club-seasons with enough coverage to rank on this measure ('o' or 's')."""
    if cs.empty:
        return cs
    return cs[cs[f"cov_{measure}"] >= MIN_COVERAGE]


def decided_by_luck(conn: sqlite3.Connection, cs: pd.DataFrame, measure: str = "o") -> list[dict]:
    """The flips alone; see _decided."""
    return _decided(conn, cs, measure)[0]


def _decided(conn: sqlite3.Connection, cs: pd.DataFrame, measure: str = "o") -> tuple[list[dict], int]:
    """
    Returns (flips, divisions examined).

    Finished divisions where re-ranking every club on expected points
    changes who went up, who won it, or who went down. Points deductions
    are carried across: they are not luck. Play-offs are left alone; they
    are a lottery of their own.
    """
    if cs.empty:
        return [], 0
    st = pd.read_sql_query(
        "SELECT season_end_year AS season, tier, club_id, position, points, status "
        "FROM standings WHERE tier <= 5 AND club_id IS NOT NULL", conn)
    merged = cs.merge(st, on=["season", "tier", "club_id"], how="inner")
    out = []
    examined = 0
    for (season, tier, _div), grp in merged.groupby(["season", "tier", "division_id"], dropna=False):
        if (grp["status"] == "In progress").any() or (grp[f"cov_{measure}"] < MIN_COVERAGE).any():
            continue
        examined += 1
        g = grp.copy()
        # Expected table: expected points plus whatever the table did to the
        # club that was not a match (a deduction).
        g["xtable"] = g[f"xpts_{measure}"] + (g["points"] - g["pts"])
        g = g.sort_values("xtable", ascending=False).reset_index(drop=True)
        g["xpos"] = np.arange(1, len(g) + 1)
        n = len(g)
        zones = [("relegated", g["status"] == "Relegated", "bottom")]
        if tier == 1:
            zones.append(("title", g["status"] == "Champions", "top"))
        else:
            zones.append(("promoted", g["status"].isin(["Champions", "Promoted"]), "top"))
        for zone, mask, end in zones:
            k = int(mask.sum())
            if not k or k >= n:
                continue
            actual = set(g.loc[mask, "club_id"])
            positions = g.loc[mask, "position"]
            # Only a zone that is a block at one end of the table is a zone of
            # the table; an expulsion halfway up is not luck.
            want = set(range(n - k + 1, n + 1)) if end == "bottom" else set(range(1, k + 1))
            if set(positions.astype(int)) != want:
                continue
            expected = set(g.iloc[n - k:]["club_id"]) if end == "bottom" else set(g.iloc[:k]["club_id"])
            if actual == expected:
                continue
            by = g.set_index("club_id")
            for cid in actual - expected:
                r = by.loc[cid]
                out.append({"season": int(season), "tier": int(tier), "zone": zone, "club_id": cid, "name": r["name"],
                            "happened": True, "pts": int(r["points"]), "xpts": round(float(r["xtable"]), 1),
                            "position": int(r["position"]), "xpos": int(r["xpos"])})
            for cid in expected - actual:
                r = by.loc[cid]
                out.append({"season": int(season), "tier": int(tier), "zone": zone, "club_id": cid, "name": r["name"],
                            "happened": False, "pts": int(r["points"]), "xpts": round(float(r["xtable"]), 1),
                            "position": int(r["position"]), "xpos": int(r["xpos"])})
    return out, examined


OUTCOMES = [("Champions", ["Champions"]), ("Promoted automatically", ["Promoted"]),
            ("Promoted in the play-offs", ["Play-off Promoted"]), ("Stayed", ["Stayed"]), ("Relegated", ["Relegated"])]


def by_outcome(conn: sqlite3.Connection, cs: pd.DataFrame) -> list[dict]:
    """
    Average luck by how the season ended. Whoever finishes at either end
    of a table was, on average, lucky or unlucky to get there: the
    extremes select for it. This is why a champion is so often 'lucky'.
    """
    r = ranked(cs, "o")
    if r.empty:
        return []
    st = pd.read_sql_query("SELECT season_end_year AS season, tier, club_id, status FROM standings "
                           "WHERE tier <= 5 AND club_id IS NOT NULL", conn)
    m = r.merge(st, on=["season", "tier", "club_id"])
    out = []
    for label, statuses in OUTCOMES:
        g = m[m["status"].isin(statuses)]
        if len(g):
            out.append({"label": label, "n": int(len(g)), "mean": round(float(g["luck_o"].mean()), 1),
                        "share_lucky": round(float((g["luck_o"] > 0).mean()), 2)})
    return out


def persistence(cs: pd.DataFrame, measure: str = "o") -> dict:
    """
    Does luck carry over? The correlation between a club's luck per game
    one season and the next, beside the same for expected points per game
    (which is ability, as the market sees it). Luck that is luck does not
    carry over.
    """
    r = ranked(cs, measure)
    if r.empty:
        return {}
    r = r.assign(lpg=r[f"luck_{measure}"] / r[f"n_{measure}"], xpg=r[f"x{measure}"] / r[f"n_{measure}"])
    per = r.groupby(["club_id", "season"])[["lpg", "xpg"]].mean().reset_index()
    nxt = per.assign(season=per["season"] - 1)
    pairs = per.merge(nxt, on=["club_id", "season"], suffixes=("", "_next"))
    if len(pairs) < 10:
        return {}
    return {"n": int(len(pairs)),
            "luck": round(float(np.corrcoef(pairs["lpg"], pairs["lpg_next"])[0, 1]), 2),
            "ability": round(float(np.corrcoef(pairs["xpg"], pairs["xpg_next"])[0, 1]), 2),
            "points": [[round(float(a), 3), round(float(b), 3)] for a, b in zip(pairs["lpg"], pairs["lpg_next"])]}


def market_beaters(cs: pd.DataFrame) -> list[dict]:
    """
    Clubs with many seasons of prices, by average luck a season. Luck is
    noise, so the standard error rides along: a club whose average is
    within two standard errors of zero has not beaten anything.
    """
    r = ranked(cs, "o")
    if r.empty:
        return []
    r = r.assign(per38=r["luck_o"] / r["n_o"] * 38)
    out = []
    for cid, grp in r.groupby("club_id"):
        if len(grp) < MIN_MARKET_SEASONS:
            continue
        v = grp["per38"].to_numpy(float)
        se = float(v.std(ddof=1) / math.sqrt(len(v)))
        out.append({"club_id": cid, "name": grp.sort_values("season")["name"].iloc[-1], "seasons": int(len(v)),
                    "mean": round(float(v.mean()), 1), "se": round(se, 1),
                    "clear": bool(abs(v.mean()) > 2 * se), "total": round(float(grp["luck_o"].sum()), 1)})
    return sorted(out, key=lambda c: -c["mean"])


def club_season_dict(row) -> dict:
    def num(v, nd=1):
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), nd)
    return {"season": int(row["season"]), "tier": int(row["tier"]), "club_id": row["club_id"], "name": row["name"],
            "played": int(row["played"]), "pts": int(row["pts"]),
            "xo": num(row["xpts_o"]) if row["cov_o"] > 0 else None,
            "xs": num(row["xpts_s"]) if row["cov_s"] > 0 else None,
            "luck_o": num(row["luck_o"]), "luck_s": num(row["luck_s"]),
            "cov_o": round(float(row["cov_o"]), 2), "cov_s": round(float(row["cov_s"]), 2)}


def assemble(conn: sqlite3.Connection, top: int = 15) -> dict:
    """Everything the page draws; {} when there are no odds."""
    df = load_matches(conn)
    cs = club_seasons(df)
    if cs.empty or ranked(cs, "o").empty:
        return {}
    names = dict(conn.execute("SELECT club_id, canonical_name FROM club_master"))
    cs["name"] = [names.get(c, n) for c, n in zip(cs["club_id"], cs["name"])]
    ro, rs = ranked(cs, "o"), ranked(cs, "s")
    newest = int(cs["season"].max())
    # Per game, scaled to a 46-game season, so a 38-game Premier League
    # season and a 46-game League Two season sit on one scale.
    ro = ro.assign(per46=ro["luck_o"] / ro["n_o"] * 46)
    finished = ro[ro["season"] < newest]

    def rows(frame):
        return [club_season_dict(r) for _, r in frame.iterrows()]

    both = cs[(cs["cov_o"] >= MIN_COVERAGE) & (cs["cov_s"] >= MIN_COVERAGE) & (cs["season"] < newest)]
    both = both.assign(gap=both["luck_o"] - both["luck_s"])
    coverage = (cs.groupby(["season", "tier"]).apply(
        lambda g: pd.Series({"o": float((g["cov_o"] >= MIN_COVERAGE).mean()),
                             "s": float((g["cov_s"] >= MIN_COVERAGE).mean())}), include_groups=False)
        .reset_index())
    decided = _decided(conn, cs, "o")
    club_ids = sorted(cs["club_id"].unique())
    idx = {c: i for i, c in enumerate(club_ids)}
    return {
        "newest": newest,
        "luckiest": rows(finished.sort_values("luck_o", ascending=False).head(top)),
        "unluckiest": rows(finished.sort_values("luck_o").head(top)),
        "luckiest_s": rows(ranked(cs[cs["season"] < newest], "s").sort_values("luck_s", ascending=False).head(top)),
        "unluckiest_s": rows(ranked(cs[cs["season"] < newest], "s").sort_values("luck_s").head(top)),
        "decided": decided[0], "decided_examined": decided[1],
        "decided_s": decided_by_luck(conn, cs, "s"),
        "outcomes": by_outcome(conn, cs),
        "persist_o": persistence(cs, "o"),
        "persist_s": persistence(cs, "s"),
        "beaters": market_beaters(cs),
        "odds_kinder": rows(both.sort_values("gap", ascending=False).head(10)),
        "shots_kinder": rows(both.sort_values("gap").head(10)),
        "current": rows(cs[cs["season"] == newest].sort_values(["tier", "luck_o"], ascending=[True, False])),
        "coverage": [{"season": int(r.season), "tier": int(r.tier), "o": round(r.o, 2), "s": round(r.s, 2)}
                     for r in coverage.itertuples()],
        "n_matches_o": int(df["ph"].notna().sum()), "n_matches_s": int(df["sh"].notna().sum()),
        "first_o": int(ro["season"].min()), "first_s": int(rs["season"].min()) if not rs.empty else None,
        "sd_o": round(float(finished["per46"].std()), 1) if len(finished) > 1 else None,
        # The scatter: every club-season, compact. [season, tier, club, played, pts, xo, xs]
        "clubs": [{"id": c, "name": names.get(c, c)} for c in club_ids],
        "scatter": [[int(r.season), int(r.tier), idx[r.club_id], int(r.played), int(r.pts),
                     None if r.cov_o < MIN_COVERAGE else round(float(r.xpts_o), 1),
                     None if r.cov_s < MIN_COVERAGE else round(float(r.xpts_s), 1)]
                    for r in cs.itertuples()],
    }
