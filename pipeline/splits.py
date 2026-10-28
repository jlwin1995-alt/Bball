"""A player's record against his own pregame projection, split by how soft the opposing defence was  ->  data/log/split_hist.csv.gz, site/data/splits.json

    python -m pipeline.splits [--backfill]

For every finished game day (after the first 30 of a season) the walk-forward model is run on the games BEFORE that day, with the day's
absentees known, and each player's projection (points, rebounds, assists, threes) is stored beside what he did and the opposing defence's
rank in the team-wide defence table that day (1 = softest of 30). Days already in the file are skipped, so a normal refresh adds one day.
splits.json then counts, for every player, how many games he went OVER his projection against soft (rank 1-10), tough (21-30) and all
defences. Display only: a walk-forward test over 2024-25 and 2025-26 found the record does not predict his next game (correlation ~0).
"""
import argparse, json, os
import numpy as np
import pandas as pd
from . import config as C
from .model import project, _prep, defence_table

HIST = "data/log/split_hist.csv.gz"
SS = ["pts", "reb", "ast", "fg3m"]
FIRST_DAYS = 30
MIN_PROJ = 15.0


def _day(games, g, d, season):
    today = g[(g.date == d) & (g.season == season)]
    slate = today[["team", "opp", "home"]].drop_duplicates("team").assign(date=d)
    hist = games[pd.to_datetime(games["date"]) < d]
    p0, _ = project(hist, slate, None, asof=d)
    ab = p0[(p0.min_s >= 15) & (p0.pplay >= 0.6) & (~p0.pid.isin(set(today.pid)))]
    inj = pd.DataFrame({"pid": ab.pid.astype(str), "name": ab["name"], "team": ab.team, "status": "Out"})
    P, _ = project(hist, slate, inj, asof=d)
    gh = _prep(hist)
    dt = defence_table(gh[gh["date"] < pd.Timestamp(d)])
    rank = {}
    for s in SS:
        v = pd.Series({t: r[s + "_raw"] for t, r in dt.items()}).sort_values(ascending=False)
        rank[s] = dict(zip(v.index, range(1, len(v) + 1)))
    act = today.drop_duplicates("pid").set_index("pid")
    rows = []
    for _, p in P[P.pid.isin(act.index) & (P["min"] >= MIN_PROJ)].iterrows():
        a = act.loc[p.pid]
        r = {"date": str(pd.Timestamp(d).date()), "season": int(season), "pid": p.pid, "opp": p.opp, "min": round(float(p["min"]), 1)}
        for s in SS:
            r[s + "_p"] = round(float(p[s]), 2); r[s + "_a"] = int(a[s]); r[s + "_rk"] = rank[s].get(p.opp, np.nan)
        rows.append(r)
    return rows


def update(games, path=HIST, max_days=None, checkpoint=25):
    games = games.astype({"pid": str}).copy()
    g = _prep(games)
    old = pd.read_csv(path, dtype={"pid": str}) if os.path.exists(path) else pd.DataFrame()
    done = set(old["date"].astype(str)) if len(old) else set()
    todo = []
    for season, gs in g.groupby("season"):
        days = sorted(gs["date"].unique())[FIRST_DAYS:]
        todo += [(d, season) for d in days if str(pd.Timestamp(d).date()) not in done]
    todo = todo[:max_days] if max_days else todo
    rows, keep = [], C.SEASON
    try:
        for i, (d, season) in enumerate(sorted(todo)):
            C.SEASON = int(season)                      # the model's season weights are relative to the season being projected
            rows += _day(games, g, d, season)
            if checkpoint and (i + 1) % checkpoint == 0:
                _save(old, rows, path); print(f"splits: {i + 1}/{len(todo)} days", flush=True)
    finally:
        C.SEASON = keep
    return _save(old, rows, path)


def _save(old, rows, path):
    out = pd.concat([old, pd.DataFrame(rows)], ignore_index=True) if rows else old
    if len(out):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        out.to_csv(path, index=False)
    return out


def counts(hist, pids):
    """{pid: {stat: {'a': [n, over], 's': [n, over], 't': [n, over]}}}: games and games OVER his projection (all / soft 1-10 / tough 21-30)."""
    h = hist[hist.pid.isin(pids)]
    res = {}
    for pid, d in h.groupby("pid"):
        o = {}
        for s in SS:
            over = (d[s + "_a"] > d[s + "_p"]).to_numpy(); rk = d[s + "_rk"].to_numpy()
            soft, tough = rk <= 10, rk >= 21
            o[s] = {"a": [int(len(d)), int(over.sum())], "s": [int(soft.sum()), int(over[soft].sum())], "t": [int(tough.sum()), int(over[tough].sum())]}
        res[pid] = o
    return res


def write(games, pids, out="site/data", path=HIST):
    hist = update(games, path)
    json.dump(counts(hist, set(pids)), open(os.path.join(out, "splits.json"), "w"), separators=(",", ":"))
    return len(hist)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    a = ap.parse_args()
    g = pd.read_csv(f"{a.raw}/games.csv", dtype={"pid": str})
    print("split_hist rows:", len(update(g)))
