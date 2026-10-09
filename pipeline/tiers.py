"""Team Tiers: offensive / defensive rating, pace and net rating per team, from box scores.

Display only: for reading a slate, not for projecting one (same call the football model made about EPA). Ratings are points
per 100 possessions, with possessions estimated as FGA + 0.44*FTA + TOV (offensive rebounds are not in the feed, so the level
runs a few percent high; the ranking is unaffected). `reliability` is the split-half correlation of each measure across a
season (odd game-days vs even game-days): how much of a team's number is signal. Low = do not lean on it.
"""
import numpy as np
import pandas as pd


def _team_games(g):
    g = g.assign(poss=g["fga"] + 0.44 * g["fta"] + g["tov"])
    tg = g.groupby(["team", "opp", "date"], as_index=False)[["poss", "pts"]].sum()
    o = tg.rename(columns={"team": "opp", "opp": "team", "pts": "pts_o", "poss": "poss_o"})[["team", "opp", "date", "pts_o", "poss_o"]]
    tg = tg.merge(o, on=["team", "opp", "date"])
    tg["off"] = tg["pts"] / tg["poss"] * 100
    tg["def"] = tg["pts_o"] / tg["poss_o"] * 100
    tg["pace"] = (tg["poss"] + tg["poss_o"]) / 2
    tg["win"] = (tg["pts"] > tg["pts_o"]).astype(int)
    n = tg.groupby("team")["date"].transform("count")
    return tg[n >= 0.5 * n.max()].sort_values("date")             # drops All-Star / exhibition clubs


def build(g):
    """g: box scores of ONE season (columns team, opp, date, pts, fga, fta, tov). Returns rows sorted by net rating."""
    tg = _team_games(g)
    if tg.empty:
        return []
    rows = []
    for team, d in tg.groupby("team"):
        off, de = d["pts"].sum() / d["poss"].sum() * 100, d["pts_o"].sum() / d["poss_o"].sum() * 100
        l10 = d.tail(10)
        rows.append({"team": team, "g": int(len(d)), "w": int(d["win"].sum()), "l": int(len(d) - d["win"].sum()),
                     "off": round(off, 1), "def": round(de, 1), "net": round(off - de, 1), "pace": round(d["pace"].mean(), 1),
                     "net10": round(l10["pts"].sum() / l10["poss"].sum() * 100 - l10["pts_o"].sum() / l10["poss_o"].sum() * 100, 1)})
    df = pd.DataFrame(rows)
    df["off_rk"] = df["off"].rank(ascending=False, method="min").astype(int)
    df["def_rk"] = df["def"].rank(method="min").astype(int)               # lower points allowed = better
    df["net_rk"] = df["net"].rank(ascending=False, method="min").astype(int)
    n = len(df)
    df["tier"] = pd.cut(df["net_rk"], [0, n * 0.2, n * 0.4, n * 0.6, n * 0.8, n + 1], labels=[1, 2, 3, 4, 5]).astype(int)
    return df.sort_values("net", ascending=False).to_dict("records")


def reliability(g):
    """Split-half correlation of off / def / net / pace across teams (odd vs even game-days). Needs a few dozen games per team."""
    tg = _team_games(g)
    if tg.empty:
        return {}
    days = {d: i for i, d in enumerate(sorted(tg["date"].unique()))}
    tg["half"] = tg["date"].map(days) % 2
    out = {}
    for k in ("off", "def", "pace"):
        a = tg[tg["half"] == 0].groupby("team")[k].mean()
        b = tg[tg["half"] == 1].groupby("team")[k].mean()
        out[k] = round(float(np.corrcoef(a.align(b, join="inner")[0], a.align(b, join="inner")[1])[0, 1]), 2)
    net = tg.assign(net=tg["off"] - tg["def"])
    a = net[net["half"] == 0].groupby("team")["net"].mean()
    b = net[net["half"] == 1].groupby("team")["net"].mean()
    a, b = a.align(b, join="inner")
    out["net"] = round(float(np.corrcoef(a, b)[0, 1]), 2)
    return out


def vs_position(g, k_min=4000.0):
    """What each defence allows per minute to guards / forwards / centers, vs the league at that position, shrunk toward 0
    by team-position minutes seen. Display only: tested as a projection input (walk-forward, 2025-26) it added nothing
    (lambda 0.0-0.5 with intervals through zero, halves disagreeing, MAE unchanged). Returns (rows, split-half reliability)."""
    from . import config as C
    from .model import norm_pos
    g = g[g["min"] > 0].copy()
    g["pos"] = g["pos"].map(norm_pos)
    n = g.groupby("opp")["date"].nunique()
    g = g[g["opp"].isin(n[n >= 0.5 * n.max()].index)]                  # real clubs only

    def ratios(d):
        tp = d.groupby(["opp", "pos"])[C.STATS + ["min"]].sum()
        lp = d.groupby("pos")[C.STATS + ["min"]].sum()
        out = {}
        for (team, pos), r in tp.iterrows():
            sh = r["min"] / (r["min"] + k_min)
            for s in C.STATS:
                lg = lp.loc[pos, s] / lp.loc[pos, "min"]
                out[(team, pos, s)] = ((r[s] / r["min"]) / lg - 1, sh)
        return out
    full = ratios(g)
    rows = {}
    for (team, pos, s), (v, sh) in full.items():
        rows.setdefault(team, {"team": team})[f"{pos}_{s}"] = round(v * sh * 100, 1)
    days = {d: i for i, d in enumerate(sorted(g["date"].unique()))}
    h = g["date"].map(days) % 2
    a, b = ratios(g[h == 0]), ratios(g[h == 1])
    rel = {}
    for pos in ("G", "F", "C"):
        for s in C.STATS:
            keys = [k for k in a if k in b and k[1] == pos and k[2] == s]
            x = np.array([a[k][0] for k in keys]); y = np.array([b[k][0] for k in keys])
            rel[f"{pos}_{s}"] = round(float(np.corrcoef(x, y)[0, 1]), 2) if len(keys) > 5 else None
    return sorted(rows.values(), key=lambda r: r["team"]), rel
