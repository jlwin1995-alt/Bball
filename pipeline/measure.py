"""Measure how much of each matchup adjustment actually shows up, and whether projections are over-dispersed.

    python -m pipeline.measure [--raw data/raw] [--every 2] [--warmup 40] [--boot 300]

Walk-forward over the season (each day projected only from earlier games), with the defence multiplier switched to
its UNDAMPED value. For every player-game and stat we then have base = projection without any opponent adjustment,
m = the undamped multiplier, and the actual. Regressing (actual - base) on base * (m - 1) gives lambda: the share of
the adjustment that arrives. lambda = 1 means the multiplier is right; 0 means it is noise. This is how the football
model set DEF_STRENGTH (rush 0.34 ... completions 0.66), measured not guessed.

Also reported, per stat: the calibration slope of actual on base (below 1 = projections are over-dispersed, shrink
them toward the slate mean) and replication: lambda on the first and second half of the sample separately. A number
that flips between halves is not a number to ship (that is what killed EPA and the vs-TE split in the football model).
"""
import argparse
import numpy as np
import pandas as pd
from . import config as C
from .model import project, _prep


def collect(games, every=2, warmup=40, min_proj_min=15.0):
    seasons = sorted(games["season"].unique())
    saved, saved_ds = C.SEASON, dict(C.DEF_STRENGTH)
    C.SEASON = int(seasons[-1])
    C.DEF_STRENGTH = {s: 1.0 for s in C.STATS}
    try:
        g = _prep(games.astype({"pid": str}))
        days = sorted(g["date"].unique())[warmup::every]
        rows = []
        for d in days:
            today = g[g["date"] == d]
            slate = today[["team", "opp", "home"]].drop_duplicates("team").assign(date=d)
            P, _ = project(games[pd.to_datetime(games["date"]) < d], slate, None, asof=d)
            P = P[(P["min"] >= min_proj_min) & ~P["out"]]
            act = today.drop_duplicates("pid").set_index("pid")
            P = P[P["pid"].isin(act.index)]
            for s in C.STATS:
                adj = P["adj_" + s].to_numpy()
                rows.append(pd.DataFrame({"date": d, "pid": P["pid"].to_numpy(), "stat": s, "min": P["min"].to_numpy(),
                                          "m": adj, "base": P[s].to_numpy() / adj, "act": act.loc[P["pid"], s].to_numpy()}))
        return pd.concat(rows, ignore_index=True)
    finally:
        C.SEASON, C.DEF_STRENGTH = saved, saved_ds


def slope(x, y):
    """OLS slope of y on x with an intercept (the intercept absorbs the median-vs-mean bias)."""
    x = x - x.mean()
    d = (x * x).sum()
    return float((x * (y - y.mean())).sum() / d) if d > 0 else np.nan


def lam(df):
    return slope((df["base"] * (df["m"] - 1)).to_numpy(), (df["act"] - df["base"]).to_numpy())


def calib(df):
    return slope(df["base"].to_numpy(), df["act"].to_numpy())


def boot_ci(df, fn, n, seed=7):
    """95% interval, resampling whole game days (player-games on one day are not independent)."""
    rng = np.random.default_rng(seed)
    groups = [g for _, g in df.groupby("date")]
    vals = []
    for _ in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        vals.append(fn(pd.concat([groups[i] for i in pick])))
    return float(np.nanpercentile(vals, 2.5)), float(np.nanpercentile(vals, 97.5))


def report(R, boot=300):
    out = []
    for s, d in R.groupby("stat"):
        d = d.sort_values("date")
        half = d["date"].sort_values().iloc[len(d) // 2]
        lo, hi = boot_ci(d, lam, boot) if boot else (np.nan, np.nan)
        clo, chi = boot_ci(d, calib, boot) if boot else (np.nan, np.nan)
        out.append({"stat": s, "n": len(d), "lambda": lam(d), "lam_lo": lo, "lam_hi": hi,
                    "lam_1st": lam(d[d["date"] < half]), "lam_2nd": lam(d[d["date"] >= half]),
                    "calib": calib(d), "cal_lo": clo, "cal_hi": chi, "cal_1st": calib(d[d["date"] < half]), "cal_2nd": calib(d[d["date"] >= half])})
    return pd.DataFrame(out)


def apply(df, lam_, b=1.0, mu=None):
    """Projection under damping lam_ and calibration slope b (b > 1 spreads projections out around mu)."""
    p = df["base"] * (1 + (df["m"] - 1) * lam_)
    return p if b == 1.0 else mu + b * (p - mu)


def evaluate(R):
    """Fit lambda and the calibration slope on one half of the days, score MAE on the other (both directions).
    Rows: current damping, lambda fixed at 1, lambda measured, lambda measured + calibration. Lower MAE is better."""
    cuts = R["date"].drop_duplicates().sort_values()
    mid = cuts.iloc[len(cuts) // 2]
    rows = []
    for s, d in R.groupby("stat"):
        halves = [d[d["date"] < mid], d[d["date"] >= mid]]
        res = {"stat": s, "current": [], "lam=1": [], "measured": [], "meas+cal": [], "none": []}
        for tr, te in (halves, halves[::-1]):
            l = float(np.clip(lam(tr), 0.0, 1.5))
            p_tr = apply(tr, l)
            b = float(np.clip(slope(p_tr.to_numpy(), tr["act"].to_numpy()), 0.8, 1.4))
            mu = float(p_tr.mean())
            for k, p in (("current", apply(te, C.DEF_STRENGTH[s])), ("lam=1", apply(te, 1.0)), ("none", apply(te, 0.0)),
                         ("measured", apply(te, l)), ("meas+cal", apply(te, l, b, mu))):
                res[k].append(float((te["act"] - p).abs().mean()))
        rows.append({k: (v if k == "stat" else float(np.mean(v))) for k, v in res.items()})
    T = pd.DataFrame(rows).set_index("stat")
    T.loc["ALL"] = T.mean()
    return T


def main(raw="data/raw", every=2, warmup=40, boot=300):
    games = pd.read_csv(f"{raw}/games.csv", dtype={"pid": str})
    R = collect(games, every, warmup)
    print(f"{len(R) // len(C.STATS)} player-games over {R['date'].nunique()} days\n")
    T = report(R, boot)
    pd.set_option("display.width", 200)
    print("lambda = share of the opponent adjustment that arrives (1 = trust it fully, 0 = noise); [lo, hi] = 95% over game days")
    print(T[["stat", "n", "lambda", "lam_lo", "lam_hi", "lam_1st", "lam_2nd"]].round(3).to_string(index=False))
    print("\ncalibration slope of actual on projection (1 = fine, <1 = over-dispersed)")
    print(T[["stat", "calib", "cal_lo", "cal_hi", "cal_1st", "cal_2nd"]].round(3).to_string(index=False))
    print("\ncurrent DEF_STRENGTH:", C.DEF_STRENGTH)
    E = evaluate(R)
    print("\nout-of-sample MAE (fit on one half of the days, scored on the other, both directions)")
    print(E.round(4).to_string())
    return T


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--every", type=int, default=2)
    ap.add_argument("--warmup", type=int, default=40)
    ap.add_argument("--boot", type=int, default=300)
    a = ap.parse_args()
    main(a.raw, a.every, a.warmup, a.boot)
