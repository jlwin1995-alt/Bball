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


def main(start, end):
    from . import fetch_espn as E
    reg = pd.read_csv("data/raw/games.csv", dtype={"pid": str})
    pre = E.fetch_preseason(date.fromisoformat(start), date.fromisoformat(end))
    if pre.empty:
        raise SystemExit("no preseason box scores found in that window")
    f = estimate(pre, reg)
    json.dump(f, open("data/raw/preseason_minutes.json", "w"), indent=1)
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
