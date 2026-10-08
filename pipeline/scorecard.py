"""Live track record. Projections are appended to data/log/accuracy_log.csv BEFORE the games and
never rewritten; once box scores arrive each logged row is scored against two naive baselines.

Each row carries a settings stamp (hash of every knob in config.py). Change a knob and the stamp
changes, so the scorecard can tell one model's record from another's. Only the newest stamp counts
toward the headline numbers.
"""
import hashlib, json, os
import numpy as np
import pandas as pd
from . import config as C
from .model import fantasy, _prep

LOG = "data/log/accuracy_log.csv"


def stamp():
    knobs = {k: getattr(C, k) for k in dir(C) if k.isupper() and k not in ("SEASON", "CUR_START", "PRIOR_START", "PRIOR_END")}
    return hashlib.sha1(json.dumps(knobs, sort_keys=True, default=str).encode()).hexdigest()[:8]


def log_slate(P, games, today=None):
    """Append the slate's projections unless that date is already logged or already played."""
    if not len(P):
        return 0
    g = _prep(games)
    day = P["date"].iloc[0]
    if day < pd.Timestamp(C.CUR_START):
        return 0                                           # preseason: starters sit, and those games are never scored
    if day <= g["date"].max():
        return 0                                           # a projection made after tip-off is not a prediction
    old = pd.read_csv(LOG, dtype={"pid": str}) if os.path.exists(LOG) else pd.DataFrame()
    if len(old) and (pd.to_datetime(old["date"]) == day).any():
        return 0
    base = g.assign(fp=fantasy(g)).sort_values("date")
    ssn = base.groupby("pid")["fp"].mean()
    lst = base.groupby("pid")["fp"].apply(lambda x: x.tail(C.ROLLING_WINDOW).mean())
    Q = P[~P["out"] & (P["min"] > 0)].copy()
    new = pd.DataFrame({"date": day.date().isoformat(), "pid": Q["pid"], "name": Q["name"], "team": Q["team"], "min": Q["min"].round(2),
                        **{s: Q[s].round(3) for s in C.STATS}, "fp": fantasy(Q).round(3),
                        "base_season": Q["pid"].map(ssn).round(3), "base_last": Q["pid"].map(lst).round(3),
                        "stamp": stamp(), "logged_at": pd.Timestamp.now("UTC").isoformat(timespec="seconds")})
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    pd.concat([old, new]).to_csv(LOG, index=False)
    return len(new)


def score(games):
    if not os.path.exists(LOG):
        return {"weeks": [], "current": stamp(), "summary": None}
    L = pd.read_csv(LOG, dtype={"pid": str})
    g = _prep(games.astype({"pid": str}))
    g["fp_a"] = fantasy(g)
    A = g[["date", "pid", "fp_a", "min"]].rename(columns={"min": "min_a"})
    A["date"] = A["date"].dt.strftime("%Y-%m-%d")
    M = L.merge(A, on=["date", "pid"], how="left")
    M["scored"] = M["fp_a"].notna()
    M["dnp"] = ~M["scored"]
    S = M[M["scored"] & (M["min"] >= 15)].copy()
    S["e_m"] = (S["fp"] - S["fp_a"]).abs()
    S["e_s"] = (S["base_season"] - S["fp_a"]).abs()
    S["e_l"] = (S["base_last"] - S["fp_a"]).abs()
    days = []
    for (d, st), x in S.groupby(["date", "stamp"]):
        edge = (1 - x["e_m"].mean() / x["e_s"].mean()) * 100
        days.append({"date": d, "stamp": st, "current": st == stamp(), "n": int(len(x)),
                     "mae_model": round(x["e_m"].mean(), 3), "mae_season": round(x["e_s"].mean(), 3), "mae_last": round(x["e_l"].mean(), 3),
                     "edge_pct": round(edge, 1), "bias_pct": round((x["fp"].sum() - x["fp_a"].sum()) / x["fp_a"].sum() * 100, 1),
                     "over_pct": round((x["fp_a"] > x["fp"]).mean() * 100, 1),
                     "check": "SUSPECT" if edge > 15 else ""})        # >15% better than season average is more likely leakage than skill
    cur = S[S["stamp"] == stamp()]
    summ = None
    if len(cur):
        summ = {"n": int(len(cur)), "days": int(cur["date"].nunique()),
                "mae_model": round(cur["e_m"].mean(), 3), "mae_season": round(cur["e_s"].mean(), 3), "mae_last": round(cur["e_l"].mean(), 3),
                "edge_pct": round((1 - cur["e_m"].mean() / cur["e_s"].mean()) * 100, 1),
                "bias_pct": round((cur["fp"].sum() - cur["fp_a"].sum()) / cur["fp_a"].sum() * 100, 1),
                "over_pct": round((cur["fp_a"] > cur["fp"]).mean() * 100, 1)}
    pending = int(M.loc[M["dnp"], "date"].nunique())
    return {"days": sorted(days, key=lambda r: r["date"], reverse=True), "current": stamp(), "summary": summ,
            "logged_rows": int(len(L)), "unscored_days": pending}
