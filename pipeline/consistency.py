"""Player consistency tags: does a player have spikes, or does he play at the same level?  ->  site/data/consistency.json  (display only: nothing here feeds the projections)

For each player with at least MIN_G games of MIN_MIN+ minutes among his last WINDOW such games (across seasons, so early in a season it leans on last year), for fantasy points (PrizePicks weights) and
for points, rebounds and assists:
  cv         standard deviation / mean over the window. Steadier = lower. It falls as a player's level rises (a 35-FP star varies less, relatively, than a 12-FP bench player), so the tag uses
  adj        cv divided by the median cv of players at the same level (thirds of the stat's mean). adj < 1 = steadier than comparable players.
  tag        Steady (bottom third of adj), Average, Volatile (top third of adj).
  spike/dud  share of his games at or above 1.3x / at or below 0.7x his own median (fantasy points and points only; for rebounds and assists the counts are too small to read).
  shape      for Volatile players: Spiky (spikes outweigh duds by 10 points of share or more), Dud-prone (the reverse), else Boom/bust.
  floor/ceil 10th and 90th percentile of the window.
`rel` reports how much of the tag is signal: the correlation of cv between a player's odd and even games, and between his earlier and later games, on players with a full 24-game history.
The first look (Nov 21): odd/even 0.49 and earlier-vs-later 0.36 on fantasy points. Real but modest, so the tag is a description of recent games, not a forecast of the next one.
"""
import os, json
import numpy as np
import pandas as pd

WINDOW, MIN_G, MIN_MIN = 20, 8, 12
SC = {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0}           # PrizePicks fantasy scoring (config.DEFAULT_SCORING)
STATS = ["fp", "pts", "reb", "ast"]
SPIKE, DUD = 1.3, 0.7


def prep(g):
    g = g[g["min"] >= MIN_MIN].copy()
    g["fp"] = sum(w * g[c] for c, w in SC.items())
    return g.sort_values(["pid", "date"])


def _stat(x, s):
    v = x[s].astype(float).values
    m = float(v.mean()); sd = float(v.std(ddof=1)) if len(v) > 1 else 0.0
    out = {"mean": round(m, 1), "median": round(float(np.median(v)), 1), "cv": round(sd / m, 3) if m > 0 else None,
           "floor": round(float(np.percentile(v, 10)), 1), "ceil": round(float(np.percentile(v, 90)), 1)}
    if s in ("fp", "pts") and out["median"] > 0:
        out["spike"] = round(float((v >= SPIKE * out["median"]).mean()), 2); out["dud"] = round(float((v <= DUD * out["median"]).mean()), 2)
    return out


def build(g):
    g = prep(g)
    last = g.groupby("pid").tail(WINDOW)
    n = last.groupby("pid").size(); keep = n[n >= MIN_G].index
    P = {}
    for pid, x in last[last["pid"].isin(keep)].groupby("pid"):
        d = {"name": x["name"].iloc[-1], "team": x["team"].iloc[-1], "pos": x["pos"].iloc[-1], "n": int(len(x)), "last": [round(float(v), 1) for v in x["fp"].tail(10)]}
        for s in STATS: d[s] = _stat(x, s)
        P[pid] = d
    for s in STATS:                                                          # level-adjusted cv and the tag, within each stat
        ok = [(pid, p[s]) for pid, p in P.items() if p[s]["cv"] is not None and p[s]["mean"] > 0]
        if not ok: continue
        means = pd.Series({pid: v["mean"] for pid, v in ok})
        band = pd.qcut(means.rank(method="first"), 3, labels=False)
        med = {b: float(np.median([v["cv"] for pid, v in ok if band[pid] == b])) for b in (0, 1, 2)}
        adj = {pid: v["cv"] / med[band[pid]] for pid, v in ok}
        a = pd.Series(adj); lo, hi = a.quantile(1 / 3), a.quantile(2 / 3)
        for pid, v in ok:
            v["adj"] = round(adj[pid], 2)
            v["tag"] = "Steady" if adj[pid] <= lo else "Volatile" if adj[pid] >= hi else "Average"
            if v["tag"] == "Volatile" and "spike" in v:
                v["shape"] = "Spiky" if v["spike"] - v["dud"] >= 0.10 else "Dud-prone" if v["dud"] - v["spike"] >= 0.10 else "Boom/bust"
    return {"window": WINDOW, "min_games": MIN_G, "min_minutes": MIN_MIN, "players": P, "rel": reliability(g)}


def reliability(g):
    """cv correlation between odd / even games and earlier / later games, players with 24+ qualifying games (fantasy points)."""
    rows = []
    for pid, d in g.groupby("pid"):
        x = d["fp"].tail(24).values
        if len(x) < 24 or x.mean() <= 0: continue
        cv = lambda v: v.std(ddof=1) / v.mean()
        rows.append((cv(x[0::2]), cv(x[1::2]), cv(x[:12]), cv(x[12:])))
    if len(rows) < 20: return {}
    r = np.array(rows)
    return {"odd_even": round(float(np.corrcoef(r[:, 0], r[:, 1])[0, 1]), 2), "earlier_later": round(float(np.corrcoef(r[:, 2], r[:, 3])[0, 1]), 2), "players": len(r)}


def main(raw="data/raw", out="site/data"):
    g = pd.read_csv(f"{raw}/games.csv", dtype={"pid": str})
    res = build(g)
    os.makedirs(out, exist_ok=True)
    with open(f"{out}/consistency.json", "w") as f: json.dump(res, f, separators=(",", ":"))
    P = res["players"]; tags = pd.Series([p["fp"].get("tag") for p in P.values()]).value_counts().to_dict()
    print(f"consistency: {len(P)} players, FP tags {tags}, reliability {res['rel']}")


if __name__ == "__main__":
    main()
