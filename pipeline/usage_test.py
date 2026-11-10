"""General over-projection and the absent-player usage pass (config.GENERAL_SHRINK, config.USAGE_PASS), v2.

    python -m pipeline.usage_test [season] [step_days]

Walk-forward over one season. Rotation players who did not play (min_s >= 15, played 60%+ of the last 20 team games) are treated as known Out. project() is run with both features off and on;
the present players projected for 15+ minutes are scored on fantasy points (PrizePicks scoring), by how many rotation players were out. Findings (2024-25 and 2025-26): teammate bias -1.5 FP with
nobody out, +3.2 with 4+ out, so a general shrink (points -8%, rebounds -6%, assists -5%) AND a pass-through of the absent men's production (0.43 / 0.27 / 0.34, flattened shares) are fitted together;
either alone hurts some bucket. Fitted on one season and tested on the other: fantasy-point MAE 8.03 -> 7.93 and 7.85 -> 7.77; through the real project() (pooled parameters, mildly in-sample)
every bucket improves in both seasons (-0.5% to -2.9%).
"""
import sys, copy
import pandas as pd, numpy as np
from pipeline import config as C
from pipeline.model import project, _prep, fantasy

S = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
EVERY = int(sys.argv[2]) if len(sys.argv) > 2 else 3
games = pd.read_csv("data/raw/games.csv", dtype={"pid": str}); games = games[games["season"] <= S]; C.SEASON = S
g = _prep(games); days = sorted(g[g.season == S]["date"].unique())[30::EVERY]
LAM, SHR = dict(C.USAGE_PASS or {}), dict(C.GENERAL_SHRINK or {})
rows = []
for d in days:
    today = g[g.date == d]; slate = today[["team", "opp", "home"]].drop_duplicates("team").assign(date=d)
    hist = games[pd.to_datetime(games["date"]) < d]
    C.USAGE_PASS = None; C.GENERAL_SHRINK = None
    P0, _ = project(hist, slate, None, asof=d)
    ab = P0[(P0.min_s >= 15) & (P0.pplay >= 0.6) & (~P0.pid.isin(set(today.pid)))]
    inj = pd.DataFrame({"pid": ab.pid.astype(str), "name": ab["name"], "team": ab.team, "status": "Out"})
    off, _ = project(hist, slate, inj, asof=d)
    C.USAGE_PASS = LAM; C.GENERAL_SHRINK = SHR
    on, _ = project(hist, slate, inj, asof=d)
    act = today.drop_duplicates("pid").set_index("pid"); nab = ab.groupby("team").size()
    m = (~off["out"]) & (off["min"] >= 15) & off.pid.isin(act.index)
    o, n = off[m].set_index("pid"), on[m.values].set_index("pid"); a = act.loc[o.index]
    fa, fo, fn = fantasy(a), fantasy(o), fantasy(n)
    for pid in o.index:
        rows.append(dict(n_abs=int(nab.get(o.loc[pid, "team"], 0)), fa=fa[pid], fo=fo[pid], fn=fn[pid]))
R = pd.DataFrame(rows); R["changed"] = (R.fn - R.fo).abs() > 1e-9
print(f"{S}: {len(R)} players, GENERAL_SHRINK {SHR}, USAGE_PASS {LAM}")
for lab, mk in (("no one out", R.n_abs == 0), ("1 out", R.n_abs == 1), ("2 out", R.n_abs == 2), ("3 out", R.n_abs == 3), ("4+ out", R.n_abs >= 4), ("all", R.n_abs >= 0)):
    d = R[mk]; eo, en = d.fa - d.fo, d.fa - d.fn
    print(f"  {lab:24s} n={len(d):5d}  FP MAE {eo.abs().mean():.3f} -> {en.abs().mean():.3f}   bias (actual - projected) {eo.mean():+.2f} -> {en.mean():+.2f}")
