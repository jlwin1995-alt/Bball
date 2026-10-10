"""Learn how much less the stars play in the preseason.

    python -m pipeline.preseason_minutes [--start 2025-09-28] [--end 2025-10-20]

Pulls last preseason's box scores, compares each player's preseason minutes with his regular-season average
(from data/raw/games.csv), and writes data/raw/preseason_minutes.json:

    {"T1": {"all": 0.62, "1": 0.45, "2": 0.6, "3": 0.8, "p_play": 0.71}, ...}

T1 = averages 30+ minutes, T2 = 22-30, T3 = under 22. Each ratio is preseason minutes / regular-season minutes among
games he PLAYED; "1","2","3" are the team's 1st, 2nd, 3rd+ preseason game (stars ramp up). p_play is how often a player of that
tier suited up at all. `preseason_test project` reads this file. Caveat: the baseline is this past regular season's
average for the same player (the prior-season average is not in the data), so it flatters the ratio slightly.
"""
import argparse, json
from datetime import date
import numpy as np
import pandas as pd
from . import config as C


def tier_of(mpg):
    return np.where(mpg >= C.TIER_CUTS[0], "T1", np.where(mpg >= C.TIER_CUTS[1], "T2", "T3"))


def estimate(pre, reg):
    """pre/reg: games frames. Returns the factor dict described above."""
    base = reg.groupby("pid")["min"].mean()
    pre = pre[pre["pid"].isin(base.index)].copy()
    pre["base"] = pre["pid"].map(base)
    pre["tier"] = tier_of(pre["base"])
    pre["ratio"] = pre["min"] / pre["base"]
    pre["gno"] = pre.groupby("team")["date"].rank(method="dense").clip(upper=3).astype(int).astype(str)
    tg = pre.groupby("team")["date"].nunique()                       # preseason games per team
    out = {}
    for t, d in pre.groupby("tier"):
        rows = {"all": round(float(d["ratio"].mean()), 3), "n": int(len(d))}
        for g, dd in d.groupby("gno"):
            if len(dd) >= 15:
                rows[g] = round(float(dd["ratio"].mean()), 3)
        # share of his team's preseason games he appeared in (denominator: games of the teams his tier played for)
        appear = d.groupby("pid")["date"].nunique()
        team_of = d.groupby("pid")["team"].last()
        rows["p_play"] = round(float((appear / team_of.map(tg)).clip(upper=1).mean()), 3)
        out[t] = rows
    return out


def fit_lin(frames, weights, reg):
    """Straight-line minutes model: preseason minutes = a + b * regular-season minutes (his average when he plays), weighted least
    squares over every preseason player-game. Beats the per-tier ratio (mean of per-player ratios let deep-bench players with tiny
    baselines drag the bench factor to x1.39): learned on 2025 and scored on the 2026 preseason, minutes MAE 6.7 -> 4.5."""
    reg_base = reg.groupby("pid")["min"].mean()
    xs, ys, ws = [], [], []
    for f, w in zip(frames, weights):
        f = f[f["pid"].isin(reg_base.index)]
        if len(f) and w > 0:
            xs.append(f["pid"].map(reg_base).to_numpy()); ys.append(f["min"].to_numpy()); ws.append(np.full(len(f), float(w)))
    if not xs:
        return None
    x, y, w = np.concatenate(xs), np.concatenate(ys), np.concatenate(ws)
    sw = np.sqrt(w)
    a, b = np.linalg.lstsq(np.column_stack([np.ones_like(x), x]) * sw[:, None], y * sw, rcond=None)[0]
    return [round(float(a), 2), round(float(b), 3)]


def relearn(raw="data/raw"):
    """Offline (no network): refit from the cached preseason box scores. Last preseason (preseason_games.csv) plus this one so far
    (rehearsal_games.csv, weighted x CUR_WEIGHT because preseason rest differs year to year: starters played 0.54 of normal this
    year vs 0.69 last). Keeps the legacy tier ratios in the file for reference and adds "lin": [a, b]."""
    import os
    g = f"{raw}/games.csv"; prior = f"{raw}/preseason_games.csv"; cur = f"{raw}/rehearsal_games.csv"
    if not (os.path.exists(g) and (os.path.exists(prior) or os.path.exists(cur))):
        return None
    reg = pd.read_csv(g, dtype={"pid": str})
    rd = lambda p: pd.read_csv(p, dtype={"pid": str, "event": str}) if os.path.exists(p) else pd.DataFrame(columns=["pid", "min"])
    p25, p26 = rd(prior), rd(cur)
    lin = fit_lin([p25, p26], [1.0, C.PRESEASON_CUR_WEIGHT], reg)
    path = f"{raw}/preseason_minutes.json"
    out = json.load(open(path)) if os.path.exists(path) else {}
    if len(p25) and not any(k in out for k in ("T1", "T2", "T3")):
        out.update(estimate(p25, reg))
    if lin:
        out["lin"] = lin
        out["lin_rows"] = [int(len(p25)), int(len(p26))]
    json.dump(out, open(path, "w"), indent=1)
    return out


def main(start, end):
    from . import fetch_espn as E
    reg = pd.read_csv("data/raw/games.csv", dtype={"pid": str})
    pre = E.fetch_preseason(date.fromisoformat(start), date.fromisoformat(end))
    if pre.empty:
        raise SystemExit("no preseason box scores found in that window")
    f = estimate(pre, reg)
    json.dump(f, open("data/raw/preseason_minutes.json", "w"), indent=1)
    relearn()
    print(f"{len(pre)} preseason player-games\n")
    for t in ("T1", "T2", "T3"):
        if t in f:
            print(t, f[t])
    print("\nwrote data/raw/preseason_minutes.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-09-28")
    ap.add_argument("--end", default="2025-10-20")
    a = ap.parse_args()
    main(a.start, a.end)
