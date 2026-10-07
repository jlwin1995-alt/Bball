"""Walk-forward backtest: project each game day using only earlier games, score against what happened.

    python -m pipeline.backtest [--raw data/raw] [--every 3] [--last 60] [--write-spread]

Reports, per stat and for fantasy points: MAE of the model vs two naive baselines (season average,
last-N average), Bias (mean error / mean actual) and Over % (how often the actual beat the projection).
Over % ~ 50 means Proj is a fair median for a line; Bias is measured against the MEAN, so the two differ
on right-skewed stats by design. --write-spread fits sd = a + b*proj per stat and writes spread.json,
which build.py ships to the Lines tab.
"""
import argparse, json
import numpy as np
import pandas as pd
from . import config as C
from .model import project, fantasy, _prep


def run(games, every=3, last=60, min_proj_min=15.0):
    seasons = sorted(games["season"].unique())
    saved = C.SEASON
    C.SEASON = int(seasons[-1])                      # evaluate the newest season as "current"
    try:
        g = _prep(games)
        days = sorted(g["date"].unique())
        days = days[-last:][::every]
        out = []
        for d in days:
            today = g[g["date"] == d]
            slate = pd.DataFrame({"date": d, "team": today["team"].unique()})
            slate = slate.merge(today[["team", "opp", "home"]].drop_duplicates("team"), on="team")
            hist = games[pd.to_datetime(games["date"]) < d]
            P, _ = project(hist, slate, None, asof=d)
            P = P[(P["min"] >= min_proj_min) & ~P["out"]]
            act = today.set_index("pid")
            P = P[P["pid"].isin(act.index)]
            past = _prep(hist)
            for _, p in P.iterrows():
                a = act.loc[p["pid"]]
                h = past[past["pid"] == p["pid"]]
                row = {"date": d, "pid": p["pid"]}
                for s in C.STATS:
                    row[s + "_p"], row[s + "_a"] = p[s], a[s]
                    row[s + "_season"] = h[s].mean()
                    row[s + "_last"] = h.tail(C.ROLLING_WINDOW)[s].mean()
                out.append(row)
        return pd.DataFrame(out)
    finally:
        C.SEASON = saved


def summarise(R):
    res = {}
    R = R.copy()
    for suf in ["p", "a", "season", "last"]:
        R["fp_" + suf] = sum(R[f"{s}_{suf}"] * w for s, w in C.DEFAULT_SCORING.items())
    for s in C.STATS + ["fp"]:
        a = R[s + "_a"]
        res[s] = {"n": int(len(R)),
                  "mae_model": float((R[s + "_p"] - a).abs().mean()),
                  "mae_season": float((R[s + "_season"] - a).abs().mean()),
                  "mae_last": float((R[s + "_last"] - a).abs().mean()),
                  "bias_pct": float((R[s + "_p"].sum() - a.sum()) / a.sum() * 100),
                  "over_pct": float((a > R[s + "_p"]).mean() * 100)}
    return res, R


def fit_spread(R):
    out = {}
    for s in C.STATS + ["fp"]:
        x, y = R[s + "_p"].values, (R[s + "_a"] - R[s + "_p"]).abs().values * np.sqrt(np.pi / 2)  # E|e| = sd*sqrt(2/pi)
        b, a = np.polyfit(x, y, 1)
        out[s] = [round(float(max(a, 0.05)), 3), round(float(max(b, 0.0)), 3)]
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--every", type=int, default=3)
    ap.add_argument("--last", type=int, default=60)
    ap.add_argument("--write-spread", action="store_true")
    a = ap.parse_args()
    games = pd.read_csv(f"{a.raw}/games.csv")
    R = run(games, a.every, a.last)
    res, R = summarise(R)
    print(f"{'stat':6}{'n':>6}{'MAE model':>11}{'season':>9}{'last5':>9}{'edge vs season':>16}{'Bias %':>9}{'Over %':>8}")
    for s, v in res.items():
        edge = (1 - v["mae_model"] / v["mae_season"]) * 100
        print(f"{s:6}{v['n']:>6}{v['mae_model']:>11.3f}{v['mae_season']:>9.3f}{v['mae_last']:>9.3f}{edge:>15.1f}%{v['bias_pct']:>9.1f}{v['over_pct']:>8.1f}")
    if a.write_spread:
        json.dump(fit_spread(R), open(f"{a.raw}/spread.json", "w"))
        print("wrote", f"{a.raw}/spread.json")
